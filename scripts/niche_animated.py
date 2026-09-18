#!/usr/bin/env python3
"""Ниши под простую рисованную графику: по данным сканера (Supabase) считаем для
каждой ниши семейства animated долю рисованных форматов, спрос, новичков и список
«взлетевших» каналов (возраст ≤ 24 мес, подписчики ≥ порога, v/s по свежим роликам)."""
from __future__ import annotations
import argparse, json, os, statistics, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import yaml
from dotenv import load_dotenv
from supabase import create_client
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
ap = argparse.ArgumentParser()
ap.add_argument("--min-subs", type=int, default=30_000)
ap.add_argument("--max-age-months", type=int, default=24)
ap.add_argument("--top", type=int, default=6)
ap.add_argument("--json", default="/mnt/d/youtube/cache/niche_animated.json")
a = ap.parse_args()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
cfg = yaml.safe_load((ROOT / "config" / "niches.yaml").read_text(encoding="utf-8"))
NICHES = [k for k, v in cfg["niches"].items() if v.get("family") == "animated"]
CARTOON = {"stickman_animation", "whiteboard_2d"}

def fetch(table, cols, flt=None):
    out, off = [], 0
    while True:
        q = sb.table(table).select(cols).range(off, off + 999)
        if flt: q = flt(q)
        b = q.execute().data or []
        out += b
        if len(b) < 1000: return out
        off += 1000

vids = fetch("videos", "id,channel_id,title,published_at,duration_sec,view_count,niche,lang,relevant,format",
             lambda q: q.in_("niche", NICHES).eq("lang", "en"))
chans = {c["id"]: c for c in fetch("channels", "id,title,subscriber_count,video_count,view_count,created_at,country")}
now = datetime.now(timezone.utc)
def ts(s):
    try: return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception: return None
def age_m(c):
    t = ts(c.get("created_at") or ""); return (now - t).days / 30.4 if t else None

report, out = [], {}
for n in NICHES:
    vs = [v for v in vids if v["niche"] == n and v.get("relevant") is not False]
    rel = [v for v in vs if v.get("relevant")]
    fmts = [v.get("format") for v in rel if v.get("format")]
    cartoon_share = sum(1 for f in fmts if f in CARTOON) / len(fmts) if fmts else 0.0
    demand = sum(v.get("view_count") or 0 for v in rel)
    by_ch = defaultdict(list)
    for v in rel: by_ch[v["channel_id"]].append(v)
    rows = []
    for cid, cv in by_ch.items():
        c = chans.get(cid) or {}
        subs = c.get("subscriber_count") or 0; am = age_m(c)
        views = [v.get("view_count") or 0 for v in cv]
        cf = [v.get("format") for v in cv if v.get("format")]
        rows.append({"channel": c.get("title") or cid, "id": cid, "subs": subs, "age_months": round(am, 1) if am else None,
                     "videos_found": len(cv), "median_views": int(statistics.median(views)), "vs": round(statistics.median(views) / subs, 2) if subs else None,
                     "cartoon_share": round(sum(1 for f in cf if f in CARTOON) / len(cf), 2) if cf else None,
                     "video_count": c.get("video_count"), "country": c.get("country"),
                     "top_title": max(cv, key=lambda v: v.get("view_count") or 0)["title"][:70]})
    rising = sorted([r for r in rows if r["subs"] >= a.min_subs and r["age_months"] and r["age_months"] <= a.max_age_months
                     and (r["cartoon_share"] or 0) >= 0.5], key=lambda r: -r["subs"])
    young_views = sum(r["median_views"] * r["videos_found"] for r in rows if r["age_months"] and r["age_months"] <= 12)
    rec = {"niche": n, "n_relevant": len(rel), "n_channels": len(by_ch), "cartoon_share": round(cartoon_share, 2), "demand_views": demand,
           "newcomer_share": round(young_views / demand, 2) if demand else 0, "rising_cartoon": rising[:a.top],
           "rising_any": sorted([r for r in rows if r["subs"] >= a.min_subs and r["age_months"] and r["age_months"] <= a.max_age_months], key=lambda r: -r["subs"])[:a.top]}
    out[n] = rec; report.append(rec)

report.sort(key=lambda r: (-len(r["rising_cartoon"]), -r["cartoon_share"], -r["demand_views"]))
print(f"{'ниша':<28} {'rel':>4} {'кан':>4} {'cartoon':>7} {'спрос':>12} {'новички':>7} {'взлет.карт':>10} {'взлет.все':>9}")
for r in report:
    print(f"{r['niche']:<28} {r['n_relevant']:>4} {r['n_channels']:>4} {r['cartoon_share']:>7.0%} {r['demand_views']:>12,} {r['newcomer_share']:>7.0%} {len(r['rising_cartoon']):>10} {len(r['rising_any']):>9}")
print()
for r in report:
    if not r["rising_cartoon"]: continue
    print(f"== {r['niche']}")
    for c in r["rising_cartoon"]:
        print(f"   {c['channel'][:34]:<34} subs {c['subs']:>9,}  {c['age_months']:>5} мес  v/s {c['vs']!s:>5}  cartoon {c['cartoon_share']}  | {c['top_title']}")
Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n-> {a.json}")
