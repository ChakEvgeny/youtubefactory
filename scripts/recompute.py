#!/usr/bin/env python3
"""Пересчёт niche_scores из того, что уже лежит в Supabase. Ноль units YouTube.

Нужен после разметки relevance/format: метрики считаются только по relevant=1,
в details пишется распределение форматов в процентах.
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from scan import (ANOMALY_RATIO, BIG_SUBS, MIN_DURATION_SEC, MIN_SUBS_ANOMALY,  # noqa: E402
                  YOUNG_CHANNEL_DAYS, competition_factor, parse_ts, window_start)


def fetch_all(sb, table, cols="*", page=1000):
    out, off = [], 0
    while True:
        b = sb.table(table).select(cols).range(off, off + page - 1).execute().data
        if not b:
            break
        out += b
        if len(b) < page:
            break
        off += page
    return out


def main():
    ap = argparse.ArgumentParser(description="Пересчёт niche_scores без вызовов YouTube API")
    ap.add_argument("--langs", default="en,de")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--config", default=str(ROOT / "config" / "niches.yaml"),
                    help="матрица ниш; для отдельного канала — свой файл")
    args = ap.parse_args()
    langs = [x.strip() for x in args.langs.split(",")]

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    load_dotenv(ROOT / ".env")
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
    now = datetime.now(timezone.utc)
    cutoff = window_start(args.days)

    vids = fetch_all(sb, "videos")
    chs = {c["id"]: c for c in fetch_all(sb, "channels")}
    print(f"видео {len(vids)}, каналов {len(chs)}, окно с {cutoff.date()}")

    rows_out = []
    for niche, ncfg in cfg["niches"].items():
        nfactor = float(ncfg.get("rpm_niche_factor", 1.0))
        for lang in langs:
            rpm = float(cfg["languages"][lang]["rpm_estimate"])
            pool = [v for v in vids if v.get("lang") == lang and v.get("niche") == niche]
            if not pool:
                continue
            fresh = [v for v in pool
                     if (parse_ts(v.get("published_at")) or cutoff) >= cutoff]
            long_enough = [v for v in fresh if (v.get("duration_sec") or 0) >= MIN_DURATION_SEC]
            kept = []
            for v in long_enough:
                dal = (v.get("default_audio_language") or "").lower()
                if v.get("detected_lang") == lang or dal.startswith(lang):
                    kept.append(v)

            labeled = [v for v in kept if v.get("relevant") is not None]
            if labeled:
                scored = [v for v in kept if v.get("relevant") == 1]
                n_relevant = len(scored)
            else:
                scored, n_relevant = kept, None

            demand_views = sum(int(v.get("view_count") or 0) for v in scored)
            scored_chans = {v.get("channel_id") for v in scored if v.get("channel_id")}
            young, competition, anomalies, young_views = set(), 0, 0, 0
            for cid in scored_chans:
                ch = chs.get(cid) or {}
                created = parse_ts(ch.get("created_at"))
                if created and (now - created) < timedelta(days=YOUNG_CHANNEL_DAYS):
                    young.add(cid)
                    if int(ch.get("subscriber_count") or 0) >= BIG_SUBS:
                        competition += 1
            anom_young = 0
            for v in scored:
                ch = chs.get(v.get("channel_id")) or {}
                subs = int(ch.get("subscriber_count") or 0)
                views = int(v.get("view_count") or 0)
                if v.get("channel_id") in young:
                    young_views += views
                if subs >= MIN_SUBS_ANOMALY and views / subs >= ANOMALY_RATIO:
                    anomalies += 1
                    if v.get("channel_id") in young:
                        anom_young += 1

            newcomer_share = (young_views / demand_views) if demand_views else 0.0
            cfactor = competition_factor(competition)
            score = rpm * nfactor * demand_views * cfactor * (1 + newcomer_share)

            fmts = collections.Counter(v["format"] for v in scored if v.get("format"))
            tot_f = sum(fmts.values())
            # список пар, а не dict: JSONB не сохраняет порядок ключей
            fmt_pct = [[k, round(c * 100 / tot_f, 1)] for k, c in fmts.most_common()] if tot_f else []

            top = sorted(scored, key=lambda v: int(v.get("view_count") or 0), reverse=True)[:10]
            details = {
                "queries": ncfg.get("queries", {}).get(lang, []),
                "region": cfg["languages"][lang]["region"],
                "published_after": cutoff.strftime("%Y-%m-%d"),
                "n_raw_videos": len(pool),
                "dropped_old": len(pool) - len(fresh),
                "dropped_short": len(fresh) - len(long_enough),
                "dropped_lang": len(long_enough) - len(kept),
                "n_channels": len(scored_chans),
                "n_young_channels": len(young),
                "competition_factor": round(cfactor, 4),
                "rpm_niche_factor": nfactor,
                "n_relevant": n_relevant,
                "relevance_labeled": n_relevant is not None,
                "anomalies_young": anom_young,
                "format_pct": fmt_pct,
                "recomputed": True,
                "top_videos": [{
                    "id": v["id"], "title": v.get("title"),
                    "views": int(v.get("view_count") or 0),
                    "channel": (chs.get(v.get("channel_id")) or {}).get("title"),
                    "subs": int((chs.get(v.get("channel_id")) or {}).get("subscriber_count") or 0),
                    "format": v.get("format"),
                } for v in top],
            }
            rows_out.append({
                "lang": lang, "niche": niche, "run_date": now.date().isoformat(),
                "demand_views": demand_views, "n_videos": len(kept),
                "n_relevant": n_relevant, "competition": competition,
                "newcomer_share": round(newcomer_share, 4), "anomalies": anomalies,
                "rpm_estimate": rpm, "score": round(score, 2), "details": details,
            })

    for i in range(0, len(rows_out), 20):
        sb.table("niche_scores").upsert(rows_out[i:i + 20],
                                        on_conflict="lang,niche,run_date").execute()
    print(f"пересчитано пар: {len(rows_out)}")
    for r in sorted(rows_out, key=lambda x: -x["score"])[:8]:
        print(f"  {r['lang']} {r['niche']:<24} n_vid={r['n_videos']:>3} "
              f"n_rel={r['n_relevant']} score={r['score']:>15,.0f}")


if __name__ == "__main__":
    main()
