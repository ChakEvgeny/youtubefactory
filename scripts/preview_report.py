#!/usr/bin/env python3
"""Сводка по превью: ритм, соответствие, источники, примеры «кадр ↔ текст»."""
import collections
import json
import re
import sys
from pathlib import Path

ctx = Path(sys.argv[1])
limit = float(sys.argv[2]) if len(sys.argv) > 2 else None

sl = json.loads((ctx / "shotlist.json").read_text(encoding="utf-8"))
a = json.loads((ctx / "assets.json").read_text(encoding="utf-8"))
ts = json.loads((ctx / "timestamps.json").read_text(encoding="utf-8"))
w = ts["words"]

print("=== ГОЛОС ===")
junk = [x["word"] for x in w if re.search(r"\[|\]", x["word"])]
gaps = [w[i]["start"] - w[i - 1]["end"] for i in range(1, len(w))]
print(f"  {ts['duration']:.1f}с, {len(w)} слов, {len(w)/(ts['duration']/60):.0f} сл/мин, "
      f"tempo {ts.get('tempo')} | разметки в таймкодах: {len(junk)} | пауз >1.0с: {sum(1 for g in gaps if g > 1.0)}")

print("\n=== НАРЕЗКА (весь ролик) ===")
d = sorted(s["dur"] for s in sl)
print(f"  кадров {len(sl)} ({len(sl)/(ts['duration']/60):.1f}/мин), медиана {d[len(d)//2]:.1f}с, мин {d[0]:.1f}, макс {d[-1]:.1f}")
by = collections.defaultdict(list)
for s in sl:
    by[s["beat"]].append(s["dur"])
for b, ds in by.items():
    ds = sorted(ds)
    print(f"  {b:<7} {len(ds):>3} кадр., медиана {ds[len(ds)//2]:.1f}с  (мин {ds[0]:.1f}, макс {ds[-1]:.1f})")
print("  fx:", dict(collections.Counter(s["fx"] for s in sl)),
      "| dip-to-black:", sum(1 for s in sl if s.get("dip_before")))
runs, cur = 0, 1
for i in range(1, len(sl)):
    cur = cur + 1 if abs(sl[i]["dur"] - sl[i - 1]["dur"]) <= 1.0 else 1
    runs += cur > 3
print(f"  нарушений «±1с больше 3 подряд»: {runs}")

pv = [x for x in a if limit is None or x["start"] < limit]
print(f"\n=== ПРЕВЬЮ ({len(pv)} кадров) ===")
print("  источники:", dict(collections.Counter(x["source"] or "none" for x in pv)))
sc = [x.get("vision_score", 0) for x in pv if x.get("vision_score")]
if sc:
    print(f"  vision: медиана {sorted(sc)[len(sc)//2]}/10, мин {min(sc)}, ниже 5: {sum(1 for s in sc if s < 5)}")
print("  уникальных файлов:", len({x['file'] for x in pv if x.get('file')}),
      "| повторов:", len([x for x in pv if x.get('file')]) - len({x['file'] for x in pv if x.get('file')}))

print("\n=== ПРИМЕРЫ «КАДР ↔ ТЕКСТ» ===")
picks = [x for x in pv if x.get("source") not in (None, "motion")]
for x in picks[:: max(len(picks) // 3, 1)][:3]:
    print(f"\n  #{x['idx']} [{x['beat']}/{x['fx']}] {x['start']:.1f}–{x['end']:.1f}с ({x['dur']}с) vision {x.get('vision_score')}/10")
    print(f"    ЗВУЧИТ: {x['text'][:120]}")
    print(f"    ЗАПРОС: {x.get('final_query')}")
    print(f"    ВЫБОР:  {x.get('vision_why', '')[:95]}")

rv = ctx / "review.md"
if rv.exists():
    print("\n=== REVIEW.MD ===")
    txt = rv.read_text(encoding="utf-8")
    head = [l for l in txt.splitlines() if l.startswith("**Ритм")]
    print(" ", head[0] if head else "(нет сводной строки)")
