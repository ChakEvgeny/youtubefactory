#!/usr/bin/env python3
"""Скелеты заголовков референса: топ-20 по просмотрам Mondo Startups + Logically Answered
-> маски с плейсхолдерами (Haiku), частота и средние просмотры -> config/title_skeletons_<channel>.yaml."""
from __future__ import annotations
import json, re, statistics, sys
from collections import defaultdict
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import anthropic
from pipeline.util import claude_cost, parse_json_block

R = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/mnt/d/youtube/cache/refs")
CHANNEL = "business"
rows = []
for key in ("mondo_startups", "logically_answered"):
    lst = sorted(json.loads((R / f"list_{key}.json").read_text(encoding="utf-8")), key=lambda x: -x["views"])[:20]
    rows += [{"ch": key, **x} for x in lst]

client = anthropic.Anthropic()
prompt = ("Ниже заголовки YouTube-роликов жанра business breakdown. Для КАЖДОГО верни маску: "
          "замени конкретику плейсхолдерами {BRAND} (компания/продукт), {PERSON}, {MONEY} (сумма с валютой), "
          "{NUMBER} (число без валюты), {THING} (объект/рынок/технология), {VERB} (глагол краха/провала: Lost, Killed, Ruined...). "
          "Служебные слова, знаки, скобки, многоточия и капс оставляй как есть — они часть скелета. "
          "Кроме маски дай family — короткое имя семейства (например 'deserved_death', 'from_X_to_nothing', "
          "'finally_bursting', 'how_brand_lost', 'backfires', 'no_one_uses'). Одинаковые по структуре заголовки "
          "должны получить ОДИНАКОВУЮ маску. Верни ТОЛЬКО JSON: {\"items\":[{\"i\":0,\"mask\":\"...\",\"family\":\"...\"}]}\n\n"
          + "\n".join(f"{i}. {r['title']}" for i, r in enumerate(rows)))
r = client.messages.create(model="claude-haiku-4-5", max_tokens=4000, messages=[{"role": "user", "content": prompt}])
cost = claude_cost("claude-haiku-4-5", r.usage)
items = parse_json_block("".join(b.text for b in r.content if b.type == "text"))["items"]
for it in items:
    rows[it["i"]]["mask"], rows[it["i"]]["family"] = it["mask"], it["family"]

# второй проход: 40 масок -> ≤10 семейств с одной канонической маской каждое
prompt2 = ("Вот маски заголовков и их семейства. Сведи их к НЕ БОЛЕЕ ЧЕМ 10 семействам: близкие по структуре "
           "объединяй, у каждого семейства — одна каноническая маска (с теми же плейсхолдерами) и список номеров "
           "исходных заголовков. Верни ТОЛЬКО JSON: {\"families\":[{\"family\":\"...\",\"mask\":\"...\",\"items\":[0,3]}]}\n\n"
           + "\n".join(f"{i}. [{r.get('family')}] {r.get('mask')}  <- {r['title']}" for i, r in enumerate(rows)))
r2 = client.messages.create(model="claude-haiku-4-5", max_tokens=3000, messages=[{"role": "user", "content": prompt2}])
cost += claude_cost("claude-haiku-4-5", r2.usage)
for fmly in parse_json_block("".join(b.text for b in r2.content if b.type == "text"))["families"]:
    for i in fmly["items"]:
        if 0 <= i < len(rows):
            rows[i]["family"], rows[i]["mask"] = fmly["family"], fmly["mask"]

def has_num(t): return bool(re.search(r"\d", t))
by_mask, by_family = defaultdict(list), defaultdict(list)
for x in rows:
    if "mask" in x:
        by_mask[x["mask"]].append(x); by_family[x["family"]].append(x)
sk = []
for m, xs in by_mask.items():
    sk.append({"mask": m, "family": xs[0]["family"], "count": len(xs),
               "avg_views": int(statistics.mean(v["views"] for v in xs)),
               "channels": sorted({v["ch"] for v in xs}),
               "examples": [v["title"] for v in xs[:3]]})
sk.sort(key=lambda s: (-s["count"], -s["avg_views"]))
fam = [{"family": f, "count": len(xs), "avg_views": int(statistics.mean(v["views"] for v in xs)),
        "masks": sorted({v["mask"] for v in xs})} for f, xs in by_family.items()]
fam.sort(key=lambda s: (-s["count"], -s["avg_views"]))
all_views = [x["views"] for x in rows]
out = {"channel": CHANNEL, "measured_on": "top-20 по просмотрам: Mondo Startups (12 мес) + Logically Answered (12 мес)",
       "rules": ["Заголовок ролика строится ТОЛЬКО по одной из масок ниже: плейсхолдеры заполняются фактами из brief.md.",
                 "{VERB} — только глаголы, которые подтверждает бриф (Lost/Killed/Ruined требуют факта краха, не прогноза).",
                 "Число в заголовке — только из брифа с источником.", "Длина ≤ 70 символов; капс — не больше одного слова."],
       "stats": {"titles": len(rows), "with_number": sum(1 for x in rows if has_num(x["title"])),
                 # число в заголовке против просмотров — по каналам, иначе LA (в 5 раз больше просмотров) всё перекосит
                 "number_vs_views_by_channel": {ch: {
                     "with_number": [int(statistics.median([x["views"] for x in rows if x["ch"] == ch and has_num(x["title"])] or [0])),
                                     sum(1 for x in rows if x["ch"] == ch and has_num(x["title"]))],
                     "without_number": [int(statistics.median([x["views"] for x in rows if x["ch"] == ch and not has_num(x["title"])] or [0])),
                                        sum(1 for x in rows if x["ch"] == ch and not has_num(x["title"]))]}
                     for ch in ("mondo_startups", "logically_answered")},
                 "median_len_chars": int(statistics.median(len(x["title"]) for x in rows)),
                 "with_ellipsis": sum(1 for x in rows if "..." in x["title"] or "…" in x["title"]),
                 "with_parenthesis": sum(1 for x in rows if "(" in x["title"])},
       "families": fam, "skeletons": sk}
p = ROOT / "config" / f"title_skeletons_{CHANNEL}.yaml"
p.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
print(f"{p.relative_to(ROOT)}: масок {len(sk)}, семейств {len(fam)}, ${cost:.3f}")
for f in fam[:10]: print(f"  {f['family']:<24} ×{f['count']:<3} avg {f['avg_views']:>9,}")
print("stats", out["stats"])
