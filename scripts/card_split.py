#!/usr/bin/env python3
"""Разделение карточек: что остаётся во весь экран, что уходит титром поверх кадра.

Правило снято с готовых фильмов: полноэкранная карточка — это остановка
повествования, её оправдывает только документ, который САМ является кадром,
либо структурная веха (титул, граница акта). Всё остальное — деталь, и ей
место титром сбоку, не прерывая картинку.

Меняет kind "card" -> "overlay" и снимает PIL-карточку из storyboard,
чтобы на её месте сгенерировалась настоящая картинка.
"""
from __future__ import annotations
import argparse, json, sys
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

SYS = """Ты решаешь, как показать текст в документальном фильме.

ВО ВЕСЬ ЭКРАН ("card") — только два случая:
1. ДОКУМЕНТ И ЕСТЬ КАДР: бланк, свидетельство, официальное уведомление, страница
   правил, таблица выигрышей, рекламный проспект, газетный заголовок, табло.
   Зритель должен рассматривать сам документ.
2. СТРУКТУРНАЯ ВЕХА: титульная карточка фильма, место и год в самом начале,
   вопросы-обещания из хука, граница акта.

ТИТРОМ ПОВЕРХ КАДРА ("overlay") — всё остальное:
цифры и подсчёты, суммы, счёт ставок, имена и должности, даты внутри сцены,
перечисления людей, промежуточные итоги, подписи к происходящему.
Эти сведения сопровождают действие, а не заменяют его.

Сомневаешься — ставь overlay: полноэкранных карточек в фильме и так слишком много."""


def batch(client, rows, budget):
    pr = ('Для каждого кадра верни тип. ТОЛЬКО JSON {"<i>": "card"|"overlay"} со всеми ключами.\n\n'
          + json.dumps(rows, ensure_ascii=False))
    for _ in range(3):
        with client.messages.stream(model=MODEL, max_tokens=8000, system=SYS,
                                    messages=[{"role": "user", "content": pr}]) as st:
            out = "".join(t for t in st.text_stream)
            m = st.get_final_message()
        budget["usd"] += claude_cost(MODEL, m.usage)
        try:
            res = parse_json_block(out)
        except Exception:
            continue
        if isinstance(res, dict) and all(str(x["i"]) in res for x in rows):
            return res
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    a = ap.parse_args()
    d = Path(a.dir)
    shots = json.loads((d / "timed.json").read_text(encoding="utf-8"))
    cards = [s for s in shots if s.get("kind") == "card"]
    if not cards:
        sys.exit("карточек нет")
    rows = [{"i": s["id"], "text": s.get("card_text", ""), "narr": (s.get("narr") or "")[:90],
             "visual": (s.get("visual") or "")[:90], "t": round(s.get("t_in", 0))} for s in cards]
    chunks = [rows[i:i + 20] for i in range(0, len(rows), 20)]
    budget = {"usd": 0.0}
    client = anthropic.Anthropic()
    res = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        for r in ex.map(lambda c: batch(client, c, budget), chunks):
            res.update(r)

    sb = d / "storyboard"
    moved = []
    for s in shots:
        if s.get("kind") != "card":
            continue
        if res.get(str(s["id"])) == "overlay":
            s["kind"] = "overlay"
            s["overlay_text"] = s.get("card_text", "")
            s["card_text"] = ""            # иначе генератор снова нарисует PIL-карточку
            moved.append(s["id"])
            f = sb / f"{s['id']:03d}.jpg"
            if f.exists():
                f.unlink()                 # на её месте будет настоящий кадр
    (d / "timed.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    costs.log(costs.project_of(d), "card_split", MODEL, budget["usd"], len(cards), "карточек")
    left = sum(1 for s in shots if s.get("kind") == "card")
    print(f"было карточек {len(cards)} → осталось во весь экран {left}, в титры {len(moved)}, ${budget['usd']:.2f}")
    print("  в титры:", ", ".join(str(x) for x in moved[:30]) + (" …" if len(moved) > 30 else ""))


if __name__ == "__main__":
    main()
