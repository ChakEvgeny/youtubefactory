#!/usr/bin/env python3
"""Разбор свежего скана: где ниша растёт и пускает новичков.

Для каждой ниши из переданного конфига считает спрос за окно, долю молодых
каналов, аномалии (молодой канал с просмотрами сильно выше своей медианы) и
список кандидатов на вход. Ничего не додумывает: только то, что в Supabase.
"""
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
ap.add_argument("--config", default=str(ROOT / "config" / "niches_hype.yaml"))
ap.add_argument("--young-months", type=float, default=12.0)
ap.add_argument("--days", type=int, default=90)
ap.add_argument("--out", default="/mnt/d/youtube/cache/hype_report.json")
a = ap.parse_args()

sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
NICHES = list(yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))["niches"])
now = datetime.now(timezone.utc)


def fetch(table, cols, flt=None):
    out, off = [], 0
    while True:
        q = sb.table(table).select(cols).range(off, off + 999)
        if flt:
            q = flt(q)
        b = q.execute().data or []
        out += b
        if len(b) < 1000:
            return out
        off += 1000


def ts(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except Exception:
        return None


vids = fetch("videos", "id,channel_id,title,published_at,duration_sec,view_count,niche,lang,relevant",
             lambda q: q.in_("niche", NICHES).eq("lang", "en"))
chans = {c["id"]: c for c in fetch("channels", "id,title,subscriber_count,video_count,view_count,created_at,country")}

report = {}
for n in NICHES:
    vs = [v for v in vids if v["niche"] == n and v.get("relevant") is not False
          and (v.get("view_count") or 0) > 0
          and (v.get("duration_sec") or 0) >= 480          # только длинный формат
          and (lambda t: t is not None and (now - t).days <= a.days)(ts(v.get("published_at")))]
    if not vs:
        report[n] = {"videos": 0}
        continue
    by_ch = defaultdict(list)
    for v in vs:
        by_ch[v["channel_id"]].append(v)

    rows, young = [], 0
    for cid, cv in by_ch.items():
        c = chans.get(cid) or {}
        t = ts(c.get("created_at"))
        age = (now - t).days / 30.4 if t else None
        views = [v.get("view_count") or 0 for v in cv]
        subs = c.get("subscriber_count") or 0
        is_young = age is not None and age <= a.young_months
        young += int(is_young)
        rows.append({
            "channel": c.get("title") or cid, "id": cid, "subs": subs,
            "age_months": round(age, 1) if age is not None else None,
            "videos_in_scan": len(cv), "best": max(views), "median": statistics.median(views),
            "v_per_sub": round(max(views) / subs, 2) if subs else None,
            "young": is_young,
            "top_title": max(cv, key=lambda v: v.get("view_count") or 0)["title"][:70],
            "dur_min": round(statistics.median([(v.get("duration_sec") or 0) for v in cv]) / 60),
        })
    rows.sort(key=lambda r: -r["best"])
    report[n] = {
        "videos": len(vs),
        "views_window": sum(v.get("view_count") or 0 for v in vs),
        "channels": len(rows),
        "newcomer_share": round(young / len(rows), 2),
        "median_video_views": int(statistics.median([v.get("view_count") or 0 for v in vs])),
        "median_duration_min": round(statistics.median([(v.get("duration_sec") or 0) for v in vs]) / 60),
        "top_channels": rows[:6],
        "young_hits": [r for r in rows if r["young"] and r["best"] >= 100_000][:6],
        "top_videos": [{"views": v.get("view_count"), "min": round((v.get("duration_sec") or 0)/60),
                        "title": v["title"][:80],
                        "channel": (chans.get(v["channel_id"]) or {}).get("title", "")[:28]}
                       for v in sorted(vs, key=lambda v: -(v.get("view_count") or 0))[:5]],
    }

Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"{'ниша':<22}{'видео':>6}{'просм. за окно':>16}{'медиана':>10}{'кан.':>6}{'новички':>9}{'мин':>5}")
for n, r in sorted(report.items(), key=lambda kv: -(kv[1].get("views_window") or 0)):
    if not r.get("videos"):
        print(f"{n:<22}{'—':>6}")
        continue
    print(f"{n:<22}{r['videos']:>6}{r['views_window']:>16,}{r['median_video_views']:>10,}"
          f"{r['channels']:>6}{r['newcomer_share']:>9}{r['median_duration_min']:>5}")

print("\nМолодые каналы (≤%g мес) со 100k+ на ролик:" % a.young_months)
for n, r in report.items():
    for h in r.get("young_hits", []):
        print(f"  {n:<20} {h['channel'][:28]:<28} {h['age_months']:>5} мес  "
              f"{h['subs']:>9,} подп.  лучший {h['best']:>9,}  {h['dur_min']:>3} мин  {h['top_title']}")
