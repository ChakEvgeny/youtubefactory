#!/usr/bin/env python3
"""Прореживание схем в готовой раскадровке.

Зачем. Правило в explain_board.py раньше звучало «есть цифра — значит diagram»,
и схема вылезала почти на каждое предложение: на лесе 36 из 121 кадра, на
морской воде 38 из 124. Смотреть это невозможно — рисованный ролик каждые три
секунды прерывается шкалой. Квота: не больше 15% кадров.

Что делает:
1. Оставляет лучшие схемы — те, где число надо СРАВНИТЬ, а не просто назвать.
2. Остальные превращает в обычные сцены и дописывает им описание для художника.
3. Каждой оставшейся схеме проставляет bg_id — id ближайшего рисунка слева,
   поверх которого она ляжет (раньше это проставлялось руками).

После него нужно догенерировать картинки: explain_scenes.py сам возьмёт только
новые кадры, у которых ещё нет файла.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import anthropic
from pipeline.util import claude_cost, parse_json_block
from pipeline import costs

MODEL = "claude-opus-5"
QUOTA = 0.15

SYS = """Ты режиссёр рисованного объясняющего ролика. Тебе дают список кадров,
которые сейчас помечены как схемы (shкала, счётчик, арифметика). Схем слишком
много — ролик превращается в презентацию. Надо оставить только лучшие.

Схему СТОИТ оставить, если выполнено всё сразу:
1) число — суть кадра, а не упоминание вскользь;
2) на слух масштаб не считывается: нужно сравнить две величины, показать долю
   от целого или провести арифметику в несколько строк;
3) она не дублирует соседнюю схему.

Схему НАДО убрать, если число названо мимоходом ("три часа", "в 1962 году"),
если это просто крупная надпись без сравнения, или если рядом уже есть схема.

Для каждого убранного кадра напиши visual — описание рисунка для художника
на английском, 12-25 слов, без текста и цифр в кадре. Оно должно продолжать
соседние кадры по смыслу, а не иллюстрировать число.

Верни ТОЛЬКО JSON: {"keep": [id, ...], "drop": [{"id": N, "visual": "..."}]}
Суммарно keep + drop = все поданные id."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--quota", type=float, default=QUOTA)
    a = ap.parse_args()
    d = Path(a.dir)
    src = d / "timed.json" if (d / "timed.json").exists() else d / "board.json"
    shots = json.loads(src.read_text(encoding="utf-8"))

    dias = [s for s in shots if s["kind"] == "diagram"]
    limit = max(int(len(shots) * a.quota), 1)
    print(f"кадров {len(shots)}, схем {len(dias)} ({len(dias)/len(shots)*100:.0f}%), квота {limit}")
    if len(dias) <= limit:
        print("схем и так в пределах квоты — трогать нечего")
    else:
        ctx = [{"id": s["id"], "narr": s["narr"], "diagram": s.get("diagram")} for s in dias]
        msg = (f"Всего кадров в ролике: {len(shots)}. Оставить можно не больше {limit} схем.\n\n"
               + json.dumps(ctx, ensure_ascii=False, indent=1))
        cl = anthropic.Anthropic()
        with cl.messages.stream(model=MODEL, max_tokens=16000, system=SYS,
                                messages=[{"role": "user", "content": msg}]) as st:
            out = "".join(t for t in st.text_stream)
            m = st.get_final_message()
        res = parse_json_block(out)
        usd = claude_cost(MODEL, m.usage)
        keep = set(res.get("keep", []))
        drop = {x["id"]: x["visual"] for x in res.get("drop", [])}
        by_id = {s["id"]: s for s in shots}
        for i, vis in drop.items():
            s = by_id.get(i)
            if not s or s["kind"] != "diagram":
                continue
            s["kind"] = "scene"; s["visual"] = vis; s["diagram"] = None
        print(f"оставлено схем {len([s for s in shots if s['kind']=='diagram'])}, "
              f"переведено в рисунки {len(drop)}, ${usd:.2f}")
        costs.log(costs.project_of(d), "trim", MODEL, usd, len(dias), "схем")

    # bg_id — ближайший рисунок слева. Без него схема ищет картинку по своему id,
    # которой не существует: картинки рисуются только для кадров kind=scene.
    last = None
    fixed = 0
    for s in shots:
        if s["kind"] == "scene":
            last = s["id"]
        elif s["kind"] == "diagram":
            if last is None:
                nxt = next((x["id"] for x in shots if x["kind"] == "scene"), None)
                if nxt is None:
                    continue
                s["bg_id"] = nxt
            else:
                s["bg_id"] = last
            fixed += 1
    print(f"bg_id проставлен у {fixed} схем")

    (d / "timed.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    n_sc = len([s for s in shots if s["kind"] == "scene"])
    have = len(list((d / "scenes").glob("*.jpg"))) if (d / "scenes").exists() else 0
    print(f"сцен теперь {n_sc}, картинок на диске {have} — догенерировать {max(n_sc-have,0)}")


if __name__ == "__main__":
    main()
