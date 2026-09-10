#!/usr/bin/env python3
"""Замер длины, mid-roll и «числа в заголовке/обложке» против просмотров по спискам
референсов (12 мес) + Haiku vision по обложкам топ-20. Пишет refs/length.json."""
from __future__ import annotations
import base64, json, re, statistics, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import anthropic
from pipeline.util import claude_cost, parse_json_block

R = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/mnt/d/youtube/cache/refs")
BINS = [(0, 8, "<8"), (8, 12, "8–12"), (12, 15, "12–15"), (15, 20, "15–20"), (20, 999, "20+")]

def midrolls(dur_min: float) -> int:
    """Сколько mid-roll помещается: YouTube ставит их от 8 мин; при авторасстановке —
    примерно один слот на 2–3 мин (допущение: 1 на 2.5 мин после первой минуты)."""
    return 0 if dur_min < 8 else int((dur_min - 1) / 2.5)

def med(xs): return int(statistics.median(xs)) if xs else None
client = anthropic.Anthropic(); cost = 0.0
out = {}
for key in ("mondo_startups", "logically_answered"):
    lst = [x for x in json.loads((R / f"list_{key}.json").read_text(encoding="utf-8")) if x.get("dur")]
    mins = [x["dur"] / 60 for x in lst]
    q = statistics.quantiles(mins, n=4) if len(mins) > 3 else [0, 0, 0]
    bins = {}
    for lo, hi, name in BINS:
        xs = [x for x in lst if lo <= x["dur"] / 60 < hi]
        if xs:
            bins[name] = {"n": len(xs), "median_views": med([x["views"] for x in xs])}
    num_t = [x for x in lst if re.search(r"\d", x["title"])]
    no_t = [x for x in lst if not re.search(r"\d", x["title"])]
    # обложки топ-20: есть ли число
    top = sorted(lst, key=lambda x: -x["views"])[:20]
    th_num, th_no = [], []
    for x in top:
        p = R / "thumbs20" / f"{x['id']}.jpg"
        if not p.exists():
            continue
        r = client.messages.create(model="claude-haiku-4-5", max_tokens=120, messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(p.read_bytes()).decode()}},
            {"type": "text", "text": "Есть ли на обложке число (цифры, сумма, процент)? Верни ТОЛЬКО JSON {\"number\": true/false, \"text\": \"весь текст на обложке\"}"}]}])
        cost += claude_cost("claude-haiku-4-5", r.usage)
        d = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
        x["thumb_text"] = d.get("text", "")
        (th_num if d.get("number") else th_no).append(x)
    out[key] = {"n": len(lst), "duration_median_min": round(statistics.median(mins), 1),
                "duration_iqr_min": [round(q[0], 1), round(q[2], 1)],
                "duration_min_max": [round(min(mins), 1), round(max(mins), 1)],
                "midrolls_median": midrolls(statistics.median(mins)),
                "midrolls_at_iqr": [midrolls(q[0]), midrolls(q[2])],
                "views_by_length_bin": bins,
                "title_number": {"with": [len(num_t), med([x["views"] for x in num_t])],
                                 "without": [len(no_t), med([x["views"] for x in no_t])]},
                "thumb_number_top20": {"with": [len(th_num), med([x["views"] for x in th_num])],
                                       "without": [len(th_no), med([x["views"] for x in th_no])]},
                "thumb_texts_top20": [{"title": x["title"][:50], "views": x["views"], "thumb": x.get("thumb_text", "")} for x in top]}
out["_cost_usd"] = round(cost, 3)
(R / "length.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
for k, v in out.items():
    if k.startswith("_"): continue
    print(f"{k}: n={v['n']} длина медиана {v['duration_median_min']} мин, IQR {v['duration_iqr_min']}, mid-roll {v['midrolls_median']} ({v['midrolls_at_iqr']})")
    print("   по длине:", {b: (d['n'], d['median_views']) for b, d in v['views_by_length_bin'].items()})
    print("   число в заголовке (n, медиана просмотров):", v["title_number"], "| в обложке топ-20:", v["thumb_number_top20"])
print("cost", out["_cost_usd"])
