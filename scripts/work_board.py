#!/usr/bin/env python3
"""Раскадровка канала Terms of Employment из сценария.

Правила канала — docs/rules_terms_of_employment.md, проверяет их
scripts/lint_terms.py. Здесь они заданы модели на входе, чтобы линтеру потом
было нечего ловить.

Блок хука НЕ трогается: первые тридцать секунд собраны и утверждены, их кадры
переносятся из существующего storyboard.json как есть.

    python scripts/work_board.py <папка>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
import anthropic  # noqa: E402

from pipeline import costs  # noqa: E402
from pipeline.util import claude_cost, parse_json_block  # noqa: E402

MODEL = "claude-opus-5"
WPM = 143.0          # замеренная скорость клона Евгения, не оценка
LOCKED = "0 · хук"   # собран и утверждён, не переразбивать

SYS = """Ты режиссёр раскадровки рисованного ролика о трудовом праве. Ролик от
первого лица: автор — бывший рекрутер и HR, говорит о том, что видел изнутри.

Разбей текст блока на кадры. Текст НЕ менять и НЕ сокращать: склейка narr всех
кадров должна дословно давать исходный текст блока.

ДЛИНА КАДРА: 6–9 секунд речи (14–21 слово), ни один не длиннее 10 секунд.
В задании на блок указано, СКОЛЬКО кадров должно получиться. Это не пожелание:
отклонение больше чем на один кадр — брак.

ТИП КАДРА:
- "scene" — предмет, место, действие. Это рисует нейросеть.
- "hero" — автор в кадре. В задании на блок указано, сколько hero разрешено.
  Если разрешено 0 — hero в блоке нет вообще. Если 1 — ровно один, и он идёт на
  самую личную фразу блока («я видел», «по-моему», «за восемь лет»).
  Ведущего мы анимируем вручную, поэтому каждый лишний hero стоит денег.
- "chip" — карточка с числом поверх кадра, рисует код.
  ЖЁСТКАЯ КВОТА: не больше пяти на весь ролик, в этом блоке не больше одной.
  Ставь, только если выполнено всё сразу: число — суть кадра; на слух масштаб
  не берётся, нужно сравнить величины; соседние кадры не chip. Число,
  названное вскользь, остаётся scene.

VISUAL (для scene и hero) — описание для художника на английском, 12–25 слов.
ЖЁСТКИЕ ЗАПРЕТЫ:
- В кадре НЕТ текста, букв, цифр, вывесок, подписей, документов с читаемыми
  строками. Всё читаемое рисует код поверх.
- Кадр рисуется под СМЫСЛ строки, а не под слово из неё. Проверка: поймёт ли
  зритель мысль реплики, глядя на картинку без звука. «Четыре разных ответа» —
  это не четыре случайных предмета, а четыре РАЗНЫХ исхода одного события.
- МЕТАФОРУ БУКВАЛЬНО НЕ РИСОВАТЬ. Запрещены перетягивание каната, мешок на
  плечах, щит, весы правосудия, канатоходец, лестница, лампочка, клетка,
  разорванная цепь, горы, обрыв, страховочная сетка, песочные часы, развилка,
  двигающийся столб-граница. Если реплика отвлечённая, бери обычный предмет
  или помещение из мира работы: стол, стул, дверь, коридор, лифт, переговорную,
  ящик картотеки, папку, бейдж, конверт, доску объявлений.
- ПЕЙЗАЖА И ПРИРОДЫ НЕТ: ни полей, ни ворот в поле, ни закатов, ни горизонтов,
  ни деревьев, ни погоды.
- Карта страны — только если реплика про географию или про конкретную страну
  как место. Две карты подряд запрещены. Карта не затычка.
- Ни один мотив не повторяется дважды за ролик. Если в предыдущем кадре был
  пустой стол, в следующем пустого стола нет.
- Никакого gore, крови, тел. Никаких логотипов и чужих лиц.

Для chip: {"big":"главное число","small":"подпись до пяти слов",
"kicker":"страна или контекст до трёх слов"} — всё по-английски.

Верни ТОЛЬКО JSON: [{"narr","kind","visual","chip"}].
У scene и hero chip=null, у chip visual тоже заполняется — фишка ложится
ПОВЕРХ кадра, а не вместо него."""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out", default="board.json")
    ap.add_argument("--fit-only", action="store_true",
                    help="только подогнать готовую раскадровку под лимиты")
    a = ap.parse_args()
    d = Path(a.dir)
    if a.fit_only:
        fit(d, a.out)
        return
    raw = (d / "script.md").read_text(encoding="utf-8")

    blocks, name, buf = [], None, []
    for ln in raw.splitlines():
        if ln.startswith("## "):
            if name and buf:
                blocks.append((name, "\n".join(buf)))
            name, buf = ln[3:].split("—")[0].strip().lstrip("Блок ").strip(), []
            name = re.sub(r"^(\d+(?:\.\d+)?)\.\s*", r"\1 · ", name)
        elif name and ln.startswith("> "):
            buf.append(ln[2:])
    if name and buf:
        blocks.append((name, "\n".join(buf)))
    blocks = [b for b in blocks if b[1].strip()]
    print("блоков:", len(blocks), "—", ", ".join(b[0][:16] for b in blocks))

    # хук уже собран: берём его кадры из действующей раскадровки
    old = json.loads((d / "storyboard.json").read_text(encoding="utf-8"))
    hook = sorted([s for s in old if s.get("block") == LOCKED], key=lambda s: s["t_in"])
    print(f"хук перенесён без изменений: {len(hook)} кадров")

    client = anthropic.Anthropic()
    budget = {"usd": 0.0}

    def go(txt):
        for _ in range(3):
            with client.messages.stream(model=MODEL, max_tokens=16000, system=SYS,
                                        messages=[{"role": "user", "content": txt}]) as s:
                out = "".join(t for t in s.text_stream)
                m = s.get_final_message()
            budget["usd"] += claude_cost(MODEL, m.usage)
            try:
                r = parse_json_block(out)
            except Exception:
                continue
            if isinstance(r, list) and r:
                return r
        return []

    todo = [b for b in blocks if not b[0].startswith("0 ")]

    # бюджет кадров и появлений ведущего считаем сами, иначе модель делает
    # вдвое больше кадров и сажает ведущего в каждый второй
    HERO_TOTAL = 7
    личное = [bool(re.search(r"\b(I|I'm|I've|my|me)\b", txt)) for _, txt in todo]
    hero_left = HERO_TOTAL
    tasks = []
    for (bname, txt), personal in zip(todo, личное):
        sec = len(txt.split()) / WPM * 60
        n = max(1, round(sec / 8))
        h = 1 if (personal and hero_left > 0) else 0
        hero_left -= h
        tasks.append(f"БЛОК: {bname}\nКАДРОВ В БЛОКЕ: {n}\nHERO РАЗРЕШЕНО: {h}\n\n{txt}")
        print(f"  {bname:<22} {sec:5.0f} с -> {n:>2} кадров, hero {h}")

    with ThreadPoolExecutor(max_workers=3) as ex:
        parts = list(ex.map(go, tasks))

    shots = [dict(s) for s in hook]
    for (bname, _), part in zip(todo, parts):
        for s in part:
            s["block"] = bname
            shots.append(s)

    t = round(hook[-1]["t_in"] + hook[-1]["dur"], 2) if hook else 0.0
    nid = max([s["id"] for s in shots if "id" in s] or [0])
    for s in shots:
        if s.get("block") == LOCKED:
            continue
        nid += 1
        w = len((s.get("narr") or "").split())
        s["id"] = nid
        s["dur"] = round(max(w / WPM * 60, 2.0), 2)
        s["t_in"] = round(t, 2)
        t = round(t + s["dur"], 2)

    (d / a.out).write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    costs.log("work", "board", MODEL, budget["usd"], len(shots), "кадров")
    from collections import Counter
    c = Counter(s.get("kind") for s in shots)
    print(f"кадров {len(shots)}, хронометраж {int(t)//60}:{int(t)%60:02d}, "
          + ", ".join(f"{k} {v}" for k, v in c.most_common()) + f", ${budget['usd']:.2f}")



def fit(d: Path, out: str, max_shots: int = 100, hard: float = 9.5) -> None:
    """Подгон готовой раскадровки под лимиты правил: слишком длинный кадр
    делится по границе слова, слишком дробные соседи склеиваются. Блок хука
    не трогается — первые тридцать секунд собраны и утверждены."""
    sb = json.loads((d / out).read_text(encoding="utf-8"))
    locked = [s for s in sb if str(s.get("block", "")).startswith("0 ")]
    rest = [s for s in sb if s not in locked]
    nid = max(s["id"] for s in sb)

    def secs(s):
        return len((s.get("narr") or "").split()) / WPM * 60

    # 1. делим всё, что длиннее потолка, пополам по границе слова
    grown = []
    for s in rest:
        if secs(s) <= hard:
            grown.append(s)
            continue
        w = (s.get("narr") or "").split()
        k = len(w) // 2
        a, b = dict(s), dict(s)
        a["narr"], b["narr"] = " ".join(w[:k]), " ".join(w[k:])
        nid += 1
        b["id"] = nid
        b["chip"] = None          # фишка остаётся на первой половине
        grown += [a, b]
    rest = grown

    # 2. склеиваем самых коротких соседей внутри блока, пока кадров слишком много
    while len(locked) + len(rest) > max_shots:
        best, bi = None, None
        for i in range(len(rest) - 1):
            a, b = rest[i], rest[i + 1]
            if a.get("block") != b.get("block"):
                continue
            if a.get("kind") == "hero" or b.get("kind") == "hero":
                continue          # ведущего не сливаем: каждый такой кадр анимируется
            tot = secs(a) + secs(b)
            if tot > hard:
                continue
            if best is None or tot < best:
                best, bi = tot, i
        if bi is None:
            break
        a, b = rest[bi], rest[bi + 1]
        a["narr"] = (a.get("narr") or "") + " " + (b.get("narr") or "")
        a["chip"] = a.get("chip") or b.get("chip")
        del rest[bi + 1]

    t = round(locked[-1]["t_in"] + locked[-1]["dur"], 2) if locked else 0.0
    for s in rest:
        s["dur"] = round(max(secs(s), 2.0), 2)
        s["t_in"] = round(t, 2)
        t = round(t + s["dur"], 2)
    (d / out).write_text(json.dumps(locked + rest, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    print(f"после подгона: {len(locked) + len(rest)} кадров, "
          f"{int(t)//60}:{int(t)%60:02d}")

if __name__ == "__main__":
    main()
