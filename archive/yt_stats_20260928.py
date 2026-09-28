#!/usr/bin/env python3
"""Статистика по всем роликам каналов через YouTube Analytics API — вместо скриншотов Studio.

По каждому ролику: показы, CTR значка, просмотры, среднее время и % просмотра,
удержание на 30-й секунде, подписки, источники трафика. Сверка с порогами дня 21
из CLAUDE.md (CTR ≥ 4%, 30-я секунда ≥ 60%, средний % ≥ 40%).

Данные Analytics отстают от Studio на 1–3 дня: у свежих роликов строки пустые.

  python scripts/yt_stats.py                 # все каналы
  python scripts/yt_stats.py survival heists
Результат: /mnt/d/youtube/stats/<дата>.md и .json
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from yt_publish import creds
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

CHANNELS = ["explain", "survival", "heists"]
OUT = Path("/mnt/d/youtube/stats")
TH = {"ctr": 4.0, "r30": 60.0, "avgpct": 40.0}


def iso_dur(s: str) -> int:
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    h, mi, se = (int(x or 0) for x in m.groups()) if m else (0, 0, 0)
    return h * 3600 + mi * 60 + se


def q(ya, **kw):
    try:
        return ya.reports().query(ids="channel==MINE", **kw).execute().get("rows") or []
    except HttpError as e:
        return {"error": str(e)[:160]}


def channel_report(name: str) -> dict:
    c = creds(name)
    yt = build("youtube", "v3", credentials=c)
    ya = build("youtubeAnalytics", "v2", credentials=c)
    ch = yt.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()["items"][0]
    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=up, maxResults=50, pageToken=token).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        token = r.get("nextPageToken")
        if not token:
            break
    vids = []
    for k in range(0, len(ids), 50):
        vids += yt.videos().list(part="snippet,statistics,contentDetails,status",
                                 id=",".join(ids[k:k + 50])).execute()["items"]
    start, end = "2026-01-01", time.strftime("%Y-%m-%d")
    rows = []
    for v in vids:
        vid = v["id"]; dur = iso_dur(v["contentDetails"]["duration"])
        base = q(ya, startDate=start, endDate=end, filters=f"video=={vid}",
                 metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained")
        # показы и CTR значка Analytics API не отдаёт («query is not supported»,
        # проверено 2026-09-19) — они есть только в YouTube Reporting API (отчёт
        # channel_reach_basic_a1, ежесуточные файлы); пока колонки пустые
        imp = []
        src = q(ya, startDate=start, endDate=end, filters=f"video=={vid}",
                dimensions="insightTrafficSourceType", metrics="views", sort="-views")
        ret = q(ya, startDate=start, endDate=end, filters=f"video=={vid}",
                dimensions="elapsedVideoTimeRatio", metrics="audienceWatchRatio")
        b = base[0] if isinstance(base, list) and base else [None] * 5
        i = imp[0] if isinstance(imp, list) and imp else [None, None]
        r30 = None
        if isinstance(ret, list) and ret and dur:
            target = 30 / dur
            r30 = min(ret, key=lambda x: abs(x[0] - target))[1] * 100
        rows.append({
            "id": vid, "title": v["snippet"]["title"], "published": v["snippet"]["publishedAt"][:10],
            "privacy": v["status"]["privacyStatus"], "duration": dur,
            "views_public": int(v["statistics"].get("viewCount", 0)),
            "views": b[0], "minutes": b[1], "avg_dur": b[2], "avg_pct": b[3], "subs": b[4],
            "impressions": i[0], "ctr": (i[1] * 100 if i[1] is not None and i[1] <= 1 else i[1]),
            "r30": r30,
            "sources": src if isinstance(src, list) else [],
            "errors": [x["error"] for x in (base, imp, src, ret) if isinstance(x, dict)],
        })
    return {"channel": name, "title": ch["snippet"]["title"],
            "subscribers": ch["statistics"].get("subscriberCount"), "videos": rows}


def fmt(x, suf="", nd=1):
    return "—" if x is None else (f"{x:.{nd}f}{suf}" if isinstance(x, float) else f"{x}{suf}")


def main():
    names = sys.argv[1:] or CHANNELS
    OUT.mkdir(parents=True, exist_ok=True)
    reps = [channel_report(n) for n in names]
    day = time.strftime("%Y-%m-%d")
    (OUT / f"{day}.json").write_text(json.dumps(reps, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [f"# Статистика каналов на {day}", "",
         f"Пороги дня 21: CTR ≥ {TH['ctr']}%, удержание на 30 с ≥ {TH['r30']}%, средний % ≥ {TH['avgpct']}%. "
         "✓ — порог пройден. Analytics отстаёт на 1–3 дня.", ""]
    for rep in reps:
        L += [f"## {rep['title']} — подписчиков {rep['subscribers']}", "",
              "| ролик | дата | показы | CTR | просм. | ср. время | ср. % | 30 с | подп. | источники |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for v in sorted(rep["videos"], key=lambda x: x["published"], reverse=True):
            ok = lambda val, t: "" if val is None else (" ✓" if val >= t else "")
            ad = "—" if v["avg_dur"] is None else f"{int(v['avg_dur'])//60}:{int(v['avg_dur'])%60:02d}"
            srcs = ", ".join(f"{s[0].lower().replace('_',' ')} {s[1]}" for s in v["sources"][:3]) or "—"
            L.append(f"| {v['title'][:48]} | {v['published']} | {fmt(v['impressions'])} | "
                     f"{fmt(v['ctr'],'%')}{ok(v['ctr'],TH['ctr'])} | {fmt(v['views'])} | {ad} | "
                     f"{fmt(v['avg_pct'],'%')}{ok(v['avg_pct'],TH['avgpct'])} | "
                     f"{fmt(v['r30'],'%')}{ok(v['r30'],TH['r30'])} | {fmt(v['subs'])} | {srcs} |")
        errs = {e for v in rep["videos"] for e in v["errors"]}
        if errs:
            L += ["", "Ошибки API: " + "; ".join(sorted(errs))[:400]]
        L.append("")
    (OUT / f"{day}.md").write_text("\n".join(L), encoding="utf-8")
    print(OUT / f"{day}.md")


if __name__ == "__main__":
    main()
