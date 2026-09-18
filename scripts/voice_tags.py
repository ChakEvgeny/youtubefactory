#!/usr/bin/env python3
"""Расстановка интонаций в репликах: теги eleven_v3 по смыслу строки.

Слова не меняются. Добавляются только пометки вроде [quietly], [pause],
[firmly], [thoughtful] и знаки паузы. Без них голос читает ровно и мертво.
"""
from __future__ import annotations
import json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import anthropic
from pipeline.util import claude_cost, parse_json_block

SYS = ("Ты режиссёр озвучания документального фильма. Диктор читает ровно и сухо, но НЕ монотонно: "
       "внутри абзаца есть логические ударения, короткие паузы перед цифрой и перед поворотом мысли, "
       "снижение голоса на констатации смерти и на фразах «документы молчат», лёгкое ускорение в "
       "перечислениях.\n"
       "Твоя задача — расставить в тексте пометки для синтезатора речи eleven_v3. Доступны: "
       "[pause] короткая пауза, [quietly] тише, [firmly] твёрже, [thoughtful] задумчиво, "
       "[slowly] медленнее, [flat] нарочито ровно.\n"
       "ЖЁСТКИЕ ПРАВИЛА: слова не менять, не добавлять и не убирать; не более двух пометок на реплику; "
       "в коротких репликах (до шести слов) максимум одна; [pause] ставить только между предложениями.\n"
       "ТЕМП. В КАЖДОЙ реплике должна быть хотя бы одна пометка. Реплику без пометок модель читает "
       "вдвое быстрее остальных: замерено — с пометками 74-127 слов в минуту, без них 177-250 при "
       "цели 138, и фильм звучит рвано. Там, где эмоция не нужна, ставь нейтральную: [flat] на "
       "констатации, [pause] перед цифрой или перед поворотом мысли. Наигрыша от этого не будет: "
       "[flat] и [pause] интонацию не окрашивают, они только держат темп.")


def go(chunk, budget):
    pr = ("Расставь пометки. Верни ТОЛЬКО JSON {\"<i>\":\"текст с пометками\"} со всеми ключами.\n\n"
          + json.dumps(chunk, ensure_ascii=False))
    c = anthropic.Anthropic()
    for _ in range(3):
        with c.messages.stream(model="claude-opus-5", max_tokens=16000, system=SYS,
                               messages=[{"role": "user", "content": pr}]) as s:
            out = "".join(t for t in s.text_stream); m = s.get_final_message()
        budget["usd"] += claude_cost("claude-opus-5", m.usage)
        if not out.strip():
            continue
        try:
            res = parse_json_block(out)
        except Exception:
            continue
        if isinstance(res, dict) and all(str(x["i"]) in res for x in chunk):
            return res
    return {}


def main():
    d = Path(sys.argv[1])
    r = json.loads((d / "timed.json").read_text(encoding="utf-8"))
    rows = [{"i": s["id"], "who": s.get("speaker", "narrator"), "text": s["narr"]}
            for s in r if (s.get("narr") or "").strip()]
    budget = {"usd": 0.0}
    chunks = [rows[i:i + 20] for i in range(0, len(rows), 20)]
    res = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for x in ex.map(lambda c: go(c, budget), chunks):
            res.update(x)
    n = 0
    for s in r:
        k = str(s["id"])
        if k in res and res[k].strip():
            s["narr_plain"] = s.get("narr_plain") or s["narr"]
            if res[k].strip() != s["narr"]:
                s["narr_tagged"] = res[k].strip(); n += 1
            else:
                s["narr_tagged"] = s["narr"]
    (d / "timed.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    tagged = sum(1 for s in r if "[" in (s.get("narr_tagged") or ""))
    print(f"обработано {len(res)}/{len(rows)}, с пометками {tagged}, ${budget['usd']:.2f}")
    for s in r[:6]:
        print("  ", (s.get("narr_tagged") or "")[:110])


if __name__ == "__main__":
    main()
