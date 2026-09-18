#!/usr/bin/env python3
"""Привязка кадров к локациям и персонажам — перед генерацией картинок.

Зачем: storyboard_stills подмешивает в кадр якоря. Если подать якорь героя в
пейзажный кадр, модель послушно впишет туда человека; если не подать плиту
локации, геометрия места поплывёт от кадра к кадру. Оба дефекта ловились
руками на прошлых фильмах.

Пишет в timed.json поля: loc (ключ локации или ""), chars (список ключей),
no_person (bool).
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


def batch(client, rows, locs, chars, budget):
    sysmsg = (
        "Ты размечаешь кадры документального фильма перед генерацией картинок.\n"
        "Для каждого кадра реши три вещи, опираясь ТОЛЬКО на описание кадра:\n"
        "1) loc — в какой из перечисленных локаций происходит кадр. Если ни в одной "
        "или место не важно — пустая строка.\n"
        "2) chars — какие из перечисленных персонажей ВИДНЫ в кадре. Список ключей, "
        "обычно ноль или один, редко два. Если в описании нет человека — пустой список.\n"
        "3) no_person — true, если в кадре не должно быть ни одного человека: пейзаж, "
        "пустое помещение, предмет крупно, документ. Слова вроде no people, nobody, "
        "empty, deserted в описании означают true.\n"
        "Ключи брать только из списков, ничего не выдумывать.\n\n"
        f"ЛОКАЦИИ:\n{locs}\n\nПЕРСОНАЖИ:\n{chars}"
    )
    pr = ('Верни ТОЛЬКО JSON {"<i>": {"loc":"...","chars":[...],"no_person":true|false}} '
          "со всеми ключами.\n\n" + json.dumps(rows, ensure_ascii=False))
    for _ in range(3):
        with client.messages.stream(model=MODEL, max_tokens=16000, system=sysmsg,
                                    messages=[{"role": "user", "content": pr}]) as st:
            out = "".join(t for t in st.text_stream)
            m = st.get_final_message()
        budget["usd"] += claude_cost(MODEL, m.usage)
        if not out.strip():
            continue
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
    L = json.loads((d / "locations.json").read_text(encoding="utf-8"))
    C = json.loads((d / "characters.json").read_text(encoding="utf-8"))
    locs = "\n".join(f"- {l['key']}: {l.get('name','')} — {l['prompt'][:90]}" for l in L)
    chars = "\n".join(f"- {c['key']}: {c.get('name','')} — {c['prompt'][:90]}" for c in C)

    rows = [{"i": s["id"], "visual": s.get("visual", ""), "narr": (s.get("narr") or "")[:80]}
            for s in shots if s.get("kind") not in ("card", "black")]
    chunks = [rows[i:i + 25] for i in range(0, len(rows), 25)]
    budget = {"usd": 0.0}
    client = anthropic.Anthropic()
    res = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(lambda c: batch(client, c, locs, chars, budget), chunks):
            res.update(r)

    okl = {l["key"] for l in L}
    okc = {c["key"] for c in C}
    n_loc = n_char = n_empty = 0
    for s in shots:
        r = res.get(str(s["id"]))
        if not r:
            continue
        s["loc"] = r.get("loc", "") if r.get("loc") in okl else ""
        s["chars"] = [x for x in (r.get("chars") or []) if x in okc]
        s["no_person"] = bool(r.get("no_person")) or not s["chars"]
        n_loc += bool(s["loc"]); n_char += bool(s["chars"]); n_empty += s["no_person"]
    (d / "timed.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    costs.log(costs.project_of(d), "shot_refs", MODEL, budget["usd"], len(rows), "кадров")
    print(f"размечено {len(res)}/{len(rows)} кадров, ${budget['usd']:.2f}")
    print(f"  с локацией {n_loc}, с персонажем {n_char}, безлюдных {n_empty}")


if __name__ == "__main__":
    main()
