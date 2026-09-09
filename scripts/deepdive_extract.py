#!/usr/bin/env python3
"""Выгрузка датасетов для глубокого разбора. Только Supabase, без YouTube API."""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
import yaml
from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parent.parent
NICHES = (sys.argv[2].split(",") if len(sys.argv) > 2
          else ["space_science", "business_breakdowns"])
LANG = "en"
MIN_SUBS_VS = 1000

load_dotenv(ROOT / ".env")
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
now = datetime.now(timezone.utc)

def fetch_all(t, cols="*"):
    out, off = [], 0
    while True:
        b = sb.table(t).select(cols).range(off, off+999).execute().data
        if not b: break
        out += b
        if len(b) < 1000: break
        off += 1000
    return out

def age_m(iso):
    if not iso: return None
    dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    return round((now - dt).days / 30.44, 1)

vids = fetch_all("videos")
chs = {c["id"]: c for c in fetch_all("channels")}
out = {}
for niche in NICHES:
    pool = [v for v in vids if v.get("lang") == LANG and v.get("niche") == niche
            and v.get("relevant") == 1]
    enriched = []
    for v in pool:
        ch = chs.get(v.get("channel_id")) or {}
        subs = int(ch.get("subscriber_count") or 0)
        views = int(v.get("view_count") or 0)
        enriched.append({
            "id": v["id"], "title": v.get("title"), "views": views,
            "duration": v.get("duration_sec") or 0, "format": v.get("format"),
            "channel": ch.get("title"), "channel_id": v.get("channel_id"),
            "subs": subs, "ch_age_m": age_m(ch.get("created_at")),
            "vs": round(views / subs, 1) if subs >= MIN_SUBS_VS else None,
            "published": v.get("published_at"),
            "desc": (v.get("description") or "")[:300],
        })
    top_views = sorted(enriched, key=lambda x: -x["views"])[:30]
    top_vs = sorted([e for e in enriched if e["vs"]], key=lambda x: -x["vs"])[:15]
    # каналы-цели моложе 12 мес среди релевантных
    tgt = {}
    for e in enriched:
        if e["ch_age_m"] is not None and e["ch_age_m"] < 12 and e["subs"] >= 500:
            t = tgt.setdefault(e["channel_id"], {"channel": e["channel"], "subs": e["subs"],
                                                 "age_m": e["ch_age_m"], "n": 0, "views": 0,
                                                 "best_vs": 0})
            t["n"] += 1; t["views"] += e["views"]
            t["best_vs"] = max(t["best_vs"], e["vs"] or 0)
    targets = sorted(tgt.items(), key=lambda kv: -kv[1]["best_vs"])[:6]
    out[niche] = {"n_relevant": len(enriched), "top_views": top_views, "top_vs": top_vs,
                  "targets": [{"channel_id": k, **v} for k, v in targets],
                  "all_durations": sorted(e["duration"] for e in enriched)}
    print(f"{niche:<22} relevant={len(enriched):>3}  top_views={len(top_views)}  "
          f"top_vs={len(top_vs)}  каналов-целей={len(targets)}")

dest = Path(sys.argv[1])
dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("→", dest)
