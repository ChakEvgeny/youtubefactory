#!/usr/bin/env python3
"""Раскадровка ролика Survivor's Notebook (рисованный полевой дневник).

Отличия от объясняющих роликов (explain_board.py):
1. Темп дневника: кадры 4-7 с речи, а не 3-5.
2. Инфографика — не схема на весь экран, а «клочок» (scrap): кусок бумаги
   выезжает сбоку, закрывает часть кадра, рисунок под ним остаётся.
   Идея Евгения 2026-09-18. Смерти — крестики-могилки в списке экипажа.
3. Граница блока — переворот страницы (как в интро), а не пауза.
4. Герои повторяются: описания берутся из cast.json, чтобы модель рисовала
   одних и тех же людей. Лица мелко или в сторону — живые люди, не портреты.
"""
from __future__ import annotations
import argparse, json, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import anthropic
from pipeline.util import claude_cost, parse_json_block
from pipeline import costs

MODEL = "claude-opus-5"
WPM = 166.0          # замер на ролике про Аду: 3075 слов за 18:31
FLIP = 1.0           # переворот страницы между блоками
INTRO = 4.5          # заставка канала (NotebookIntro)

# Формат по умолчанию — дневник Survivor's Notebook. Другой канал подменяет
# описание формата и клочка файлом format.json в папке проекта
# ({"format": "...", "scrap": "..."}), остальные правила общие.
FORMAT = ("документального ролика, нарисованного как страницы полевого дневника "
          "1913 года (карандаш, сепия, бледная акварель)")
SCRAP = ("инфографика на клочке бумаги, выезжает сбоку поверх ПРЕДЫДУЩЕГО рисунка "
         "и закрывает 35-45% кадра. Рисуем кодом.")

SYS = """Ты режиссёр раскадровки {FORMAT}.

Разбей текст блока на кадры по 4-7 секунд речи (11-19 слов). Текст НЕ менять
и НЕ сокращать: склейка narr всех кадров дословно даёт исходный текст.

Тип кадра:
- "scene" — рисунок страницы дневника: люди, корабль, лёд, лагерь, предмет
  крупно. Рисует нейросеть.
- "scrap" — {SCRAP}

  Клочки ставятся ТОЛЬКО по плану SCRAP_PLAN (если он дан): ровно те, что
  перечислены для этого блока, на кадре с указанной фразой. Своих не добавлять.
  Инфографика без необходимости — брак: зритель слушает историю, а не читает.

Для scene: visual — описание рисунка на английском, 14-30 слов.
  - Без текста, цифр, надписей в кадре.
  - Люди — по описаниям из CAST, дословно их приметы; лица мелко, в тени или
    отвернуты. Никаких портретов крупно.
  - БЕЗ GORE: смерть не показывать. Ни тел, ни крови, ни ран, ни похорон с
    телом. Вместо смерти — пустое место, предмет, могильный холмик с крестом
    вдали, пустая палатка.
  - Назови ОДИН ключевой предмет кадра ("key": ...) — он получит ржаво-красный
    акцент. Никогда не пробоину, не рану, не повреждение.
  - Не называй цвета, кроме ключевого предмета.
  - Метафоры НЕ рисовать буквально: «вскроет как консервную банку» — это
    корпус во льду, а не консервная банка. Рисуй то, что происходит.
  - Разнообразь планы: общий / средний / крупный предмет / вид сверху.
Для scrap: объект scrap одного из типов:
  {"type":"roster","mark":["имена, которым ставим крестик в ЭТОМ кадре"],
     "lost":["имена, отмеченные потерянными в этом кадре — пропали без вести"],
     "count":"число живых после кадра"}
  {"type":"map","points":["Point Barrow","Wrangel Island",...],"route":"drift|march|bartlett|none","note":"до 4 слов"}
  {"type":"counter","big":"крупно, до 12 знаков","small":"подпись до 5 слов"}
  {"type":"date","big":"Jan 11, 1914","small":"до 5 слов"}
  {"type":"compare","items":[{"label","value","unit"}],"note":"до 5 слов"}
  {"type":"letter","text":"цитата ТОЛЬКО дословно из FACTS"}
Все числа и тексты scrap — только из FACTS. Выдумывать запрещено.

Верни ТОЛЬКО JSON: [{"narr","kind","visual","key","scrap"}]. У scene scrap=null,
у scrap visual=null и key=null."""


def blocks_of(raw: str):
    blocks, name, buf = [], None, []
    for ln in raw.splitlines():
        if ln.startswith("## "):
            if name and buf:
                blocks.append((name, "\n".join(buf)))
            name, buf = re.sub(r"^\d+\.\s*", "", ln[3:]).strip(), []
        elif name and ln.strip():
            buf.append(ln.strip())
    if name and buf:
        blocks.append((name, "\n".join(buf)))
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    a = ap.parse_args()
    d = Path(a.dir)
    blocks = blocks_of((d / "script.md").read_text(encoding="utf-8"))
    cast = (d / "cast.json").read_text(encoding="utf-8")
    plan_f = d / "scrap_plan.json"
    plan = json.loads(plan_f.read_text(encoding="utf-8")) if plan_f.exists() else {}
    facts = json.dumps([f["fact"] for f in json.loads((d / "brief.json").read_text())["facts"]],
                       ensure_ascii=False)
    fmt = {"format": FORMAT, "scrap": SCRAP}
    if (d / "format.json").exists():
        fmt.update(json.loads((d / "format.json").read_text(encoding="utf-8")))
    sys_prompt = SYS.replace("{FORMAT}", fmt["format"]).replace("{SCRAP}", fmt["scrap"])
    print(f"блоков: {len(blocks)}")

    client = anthropic.Anthropic()
    spent = {"usd": 0.0}

    def go(b):
        name, txt = b
        sp = json.dumps(plan.get(name, []), ensure_ascii=False)
        user = (f"CAST:\n{cast}\n\nFACTS:\n{facts}\n\nSCRAP_PLAN для этого блока "
                f"(пусто — ни одного scrap):\n{sp}\n\nБЛОК «{name}»:\n{txt}")
        for _ in range(3):
            with client.messages.stream(model=MODEL, max_tokens=16000, system=sys_prompt,
                                        messages=[{"role": "user", "content": user}]) as s:
                out = "".join(s.text_stream); m = s.get_final_message()
            spent["usd"] += claude_cost(MODEL, m.usage)
            try:
                r = parse_json_block(out)
            except Exception:
                continue
            # текст не должен теряться: сверяем склейку с блоком
            if isinstance(r, list) and r and \
                    " ".join(x.get("narr", "") for x in r).split() == txt.split():
                return r
        print(f"  ! блок «{name}»: склейка не сошлась с текстом"); return r if isinstance(r, list) else []

    with ThreadPoolExecutor(max_workers=3) as ex:
        parts = list(ex.map(go, blocks))

    shots, t, bg = [], 0.0, None
    intro_after = plan.get("_intro_after", "")
    for bi, ((bname, _), part) in enumerate(zip(blocks, parts)):
        if bi:
            prev = blocks[bi - 1][0]
            if prev == intro_after:     # заставка канала сразу после хука
                shots.append({"narr": "", "kind": "intro", "block": bname})
            else:
                shots.append({"narr": "", "kind": "flip", "block": bname})
        for s in part:
            s["block"] = bname
            shots.append(s)
    for i, s in enumerate(shots, 1):
        s["id"] = i
        w = len((s.get("narr") or "").split()); s["words"] = w
        s["dur"] = {"flip": FLIP, "intro": INTRO}.get(s["kind"]) or round(max(w / WPM * 60, 2.0), 2)
        s["t_in"] = round(t, 2); s["t_out"] = round(t + s["dur"], 2); t += s["dur"]
        if s["kind"] == "scene":
            bg = s["id"]
        elif s["kind"] == "scrap":
            s["bg_id"] = bg          # клочок ложится поверх последнего рисунка

    (d / "board.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    costs.log(costs.project_of(d), "board", MODEL, spent["usd"], len(shots), "кадров")
    from collections import Counter
    c = Counter(s["kind"] for s in shots)
    print(f"кадров {len(shots)}, ~{int(t)//60}:{int(t)%60:02d}, "
          + ", ".join(f"{k} {v}" for k, v in c.most_common()) + f", ${spent['usd']:.2f}")


if __name__ == "__main__":
    main()
