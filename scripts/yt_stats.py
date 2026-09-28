#!/usr/bin/env python3
"""Недельный отчёт по каналам через YouTube Analytics API — вместо скриншотов Studio.

По каждому ролику: просмотры, среднее время и % просмотра, удержание на 30-й
секунде, источники трафика, подписки, лайки, комментарии. По каналу — сводка,
разбивка по неделям жизни ролика и сверка с порогами дня 21 из CLAUDE.md
(CTR ≥ 4%, 30-я секунда ≥ 60%, средний % ≥ 40%).

**Показов и CTR значка здесь нет.** Analytics API отвечает «Unknown identifier
(impressions)»: эти две метрики живут только в YouTube Reporting API, отчёт
`channel_reach_basic_a1`, который надо один раз завести заданием и потом
скачивать суточные файлы. Проверено 2026-09-19 и повторно 2026-09-28.

Данные Analytics отстают от Studio на 1–3 дня: скрипт сам находит последний день
с цифрами и печатает его.

  python scripts/yt_stats.py                      # все каналы, период по вчера
  python scripts/yt_stats.py --end 2026-09-28
  python scripts/yt_stats.py survival heists
Результат: /mnt/d/youtube/stats/<дата>.md и .json
"""
from __future__ import annotations
import argparse, datetime as dt, json, re, statistics, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from yt_publish import creds
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

CHANNELS = ["explain", "survival", "heists", "work"]
OUT = Path("/mnt/d/youtube/stats")
TH = {"ctr": 4.0, "r30": 60.0, "avgpct": 40.0}
# Из какой группы источников трафика считаем «рекомендации» и «поиск»
REC = {"RELATED_VIDEO", "SUGGESTED_VIDEO"}
HOME = {"BROWSE_FEATURES"}
SEARCH = {"YT_SEARCH"}
CHPAGE = {"YT_CHANNEL", "YT_OTHER_PAGE", "PLAYLIST"}
EXT = {"EXT_URL", "NO_LINK_EMBEDDED", "NO_LINK_OTHER", "EXT_APP", "SHORTS"}
# Две группы, которых не было в первой версии, а они решают всё: лента подписок
# и платный трафик. 2026-09-28 у «Press Your Luck» 99.3% просмотров оказались
# ADVERTISING, и без этой колонки ролик читался как органический хит.
SUBS = {"SUBSCRIBER"}
ADS = {"ADVERTISING", "PROMOTED"}


def iso_dur(s: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    h, mi, se = (int(x or 0) for x in m.groups()) if m else (0, 0, 0)
    return h * 3600 + mi * 60 + se


def q(ya, **kw):
    """Запрос к Analytics. Ошибку возвращаем строкой, а не роняем отчёт целиком."""
    try:
        return ya.reports().query(ids="channel==MINE", **kw).execute().get("rows") or []
    except HttpError as e:
        try:
            msg = json.loads(e.content.decode())["error"]["message"]
        except Exception:
            msg = str(e)
        return {"error": msg[:180]}


def last_day_with_data(ya, start: str, end: str):
    """Analytics отстаёт: ищем последний день, за который вообще есть просмотры."""
    rows = q(ya, startDate=start, endDate=end, dimensions="day", metrics="views", sort="day")
    if not isinstance(rows, list):
        return None
    days = [r[0] for r in rows if (r[1] or 0) > 0]
    return days[-1] if days else None


def channel_report(name: str, end: str) -> dict:
    c = creds(name)
    yt = build("youtube", "v3", credentials=c)
    ya = build("youtubeAnalytics", "v2", credentials=c)
    ch = yt.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()["items"][0]
    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=up,
                                    maxResults=50, pageToken=token).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        token = r.get("nextPageToken")
        if not token:
            break
    vids = []
    for k in range(0, len(ids), 50):
        vids += yt.videos().list(part="snippet,statistics,contentDetails,status",
                                 id=",".join(ids[k:k + 50])).execute()["items"]

    fresh = last_day_with_data(ya, "2026-01-01", end)
    rows = []
    for v in vids:
        vid = v["id"]
        dur = iso_dur(v["contentDetails"]["duration"])
        pub = v["snippet"]["publishedAt"][:10]
        # период считаем ОТ ДАТЫ ПУБЛИКАЦИИ ролика, а не от начала года:
        # иначе средние размазываются по дням, когда ролика ещё не было
        base = q(ya, startDate=pub, endDate=end, filters=f"video=={vid}",
                 metrics="views,estimatedMinutesWatched,averageViewDuration,"
                         "averageViewPercentage,subscribersGained,likes,comments")
        src = q(ya, startDate=pub, endDate=end, filters=f"video=={vid}",
                dimensions="insightTrafficSourceType", metrics="views", sort="-views")
        ret = q(ya, startDate=pub, endDate=end, filters=f"video=={vid}",
                dimensions="elapsedVideoTimeRatio", metrics="audienceWatchRatio")
        byday = q(ya, startDate=pub, endDate=end, filters=f"video=={vid}",
                  dimensions="day", metrics="views,estimatedMinutesWatched,subscribersGained",
                  sort="day")
        b = base[0] if isinstance(base, list) and base else [None] * 7
        r30 = None
        if isinstance(ret, list) and ret and dur:
            # точку 30 с берём как ближайшую долю от длины ролика
            target = 30 / dur
            r30 = min(ret, key=lambda x: abs(x[0] - target))[1] * 100
        d0 = dt.date.fromisoformat(pub)
        week = {"1": [0, 0, 0], "2": [0, 0, 0], "3+": [0, 0, 0]}
        if isinstance(byday, list):
            for day, vw, mins, subs in byday:
                n = (dt.date.fromisoformat(day) - d0).days
                k = "1" if n < 7 else ("2" if n < 14 else "3+")
                week[k] = [week[k][0] + (vw or 0), week[k][1] + (mins or 0), week[k][2] + (subs or 0)]
        tot = sum(s[1] for s in src) if isinstance(src, list) else 0
        # Органику и рекламу считаем врозь (требование Евгения 2026-09-28):
        # на «Press Your Luck» 2596 платных просмотров из 2614 делали вид, что
        # канал растёт. Реклама — это отдельный столбец, а не часть итога.
        ads_v = sum(s[1] for s in src if s[0] in ADS) if isinstance(src, list) else 0
        org_v = (b[0] - ads_v) if b[0] is not None else None
        def share(group):
            if not isinstance(src, list) or not tot:
                return None
            return round(100 * sum(s[1] for s in src if s[0] in group) / tot, 1)
        rows.append({
            "id": vid, "title": v["snippet"]["title"], "published": pub,
            "privacy": v["status"]["privacyStatus"], "duration": dur,
            "days_live": (dt.date.fromisoformat(end) - d0).days + 1,
            "views": b[0], "views_organic": org_v, "views_ads": ads_v,
            "minutes": b[1], "avg_dur": b[2], "avg_pct": b[3],
            "subs": b[4], "likes": b[5], "comments": b[6],
            "impressions": None, "ctr": None,   # см. докстроку: их отдаёт только Reporting API
            "r30": r30,
            "src_home": share(HOME), "src_rec": share(REC), "src_search": share(SEARCH),
            "src_channel": share(CHPAGE), "src_ext": share(EXT),
            "src_subs": share(SUBS), "src_ads": share(ADS),
            "sources_raw": src if isinstance(src, list) else [],
            "week": week,
            "errors": [x["error"] for x in (base, src, ret, byday) if isinstance(x, dict)],
        })
    return {"channel": name, "title": ch["snippet"]["title"],
            "subscribers": int(ch["statistics"].get("subscriberCount", 0)),
            "data_through": fresh, "videos": rows}


def fmt(x, suf="", nd=1):
    if x is None:
        return "—"
    return f"{x:.{nd}f}{suf}" if isinstance(x, float) else f"{x}{suf}"


def mmss(sec):
    return "—" if sec is None else f"{int(sec)//60}:{int(sec)%60:02d}"


NAMES = {"explain": "Why&How", "survival": "Survivor's Notebook",
         "heists": "The Case Room", "work": "Terms of Employment"}


def write_md(reps, end, path):
    """Отчёт целиком собирает скрипт, а не человек руками в редакторе."""
    fresh = sorted({r["data_through"] for r in reps if r["data_through"]})
    through = fresh[-1] if fresh else "нет данных"
    L = [f"# Недельный отчёт по каналам · данные по {through}", "",
         f"Запрошен период по {end}. Analytics отстаёт: последний день с данными — "
         f"{through}. Отсутствие строк за более поздние дни означает именно отсутствие "
         "данных, а не нули: нули API возвращает штатно.", "",
         "**Органика и реклама считаются отдельно.** Столбец «реклама» — просмотры "
         "с источником ADVERTISING; в «органике» их нет. Рост канала читается только "
         "по органике.", ""]
    for rep in reps:
        vids = sorted(rep["videos"], key=lambda x: x["published"])
        pubs = [v for v in vids if v["privacy"] == "public"]
        L += [f"## {NAMES.get(rep['channel'], rep['channel'])} — подписчиков {rep['subscribers']}", "",
              "| ролик | длина | дата | дней | органика | реклама | нед. 1 | нед. 2 | "
              "ср. время | ср. % | 30 с | подп. | лайк | комм. | рек | поиск | подписки | внеш |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for v in vids:
            if v["privacy"] != "public":
                L.append(f"| {v['title'][:44]} | {mmss(v['duration'])} | {v['published']} | — | "
                         f"*{v['privacy']}* |" + " — |" * 13)
                continue
            ok = lambda val, t: " ✓" if (val is not None and val >= t) else ""
            L.append(
                f"| {v['title'][:44]} | {mmss(v['duration'])} | {v['published']} | {v['days_live']} | "
                f"{fmt(v['views_organic'])} | {fmt(v['views_ads'])} | {v['week']['1'][0]} | "
                f"{v['week']['2'][0]} | {mmss(v['avg_dur'])} | {fmt(v['avg_pct'],'%',0)}"
                f"{ok(v['avg_pct'],TH['avgpct'])} | {fmt(v['r30'],'%',0)}{ok(v['r30'],TH['r30'])} | "
                f"{fmt(v['subs'])} | {fmt(v['likes'])} | {fmt(v['comments'])} | "
                f"{fmt(v['src_rec'],'%',0)} | {fmt(v['src_search'],'%',0)} | "
                f"{fmt(v['src_subs'],'%',0)} | {fmt(v['src_ext'],'%',0)} |")
        org = sum(v["views_organic"] or 0 for v in pubs)
        ads = sum(v["views_ads"] or 0 for v in pubs)
        pct = [v["avg_pct"] for v in pubs if v["avg_pct"] is not None]
        L += ["", f"**Сводка.** Публичных роликов {len(pubs)}. Органических просмотров "
                  f"{org}, рекламных {ads}. Часов просмотра "
                  f"{sum(v['minutes'] or 0 for v in pubs)/60:.1f}. Подписчиков "
                  f"{sum(v['subs'] or 0 for v in pubs)}, лайков "
                  f"{sum(v['likes'] or 0 for v in pubs)}, комментариев "
                  f"{sum(v['comments'] or 0 for v in pubs)}."]
        if pct:
            L.append(f"Средний процент просмотра: медиана {statistics.median(pct):.1f}%, "
                     f"разброс {min(pct):.1f}–{max(pct):.1f}%.")
        L.append("")
    L += ["## Пороги дня 21", "",
          "| канал | публичных | CTR ≥ 4% | 30 с ≥ 60% | ср. % ≥ 40% |", "|---|---|---|---|---|"]
    for rep in reps:
        pubs = [v for v in rep["videos"] if v["privacy"] == "public"]
        r30 = [v["r30"] for v in pubs if v["r30"] is not None]
        pct = [v["avg_pct"] for v in pubs if v["avg_pct"] is not None]
        ctr = [v["ctr"] for v in pubs if v.get("ctr") is not None]
        ctr_cell = (f"{sum(1 for x in ctr if x >= TH['ctr'])} из {len(ctr)}" if ctr
                    else "нет данных (Reporting API)")
        L.append(f"| {NAMES.get(rep['channel'], rep['channel'])} | {len(pubs)} | {ctr_cell} | "
                 f"{sum(1 for x in r30 if x >= TH['r30'])} из {len(r30)} с данными | "
                 f"{sum(1 for x in pct if x >= TH['avgpct'])} из {len(pct)} |")
    L += ["", "Удержание на 30-й секунде API строит не у всех роликов: там, где просмотров "
              "мало, кривой нет. Знаменатель — ролики с данными.", ""]
    Path(path).write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("channels", nargs="*")
    ap.add_argument("--end", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    a = ap.parse_args()
    names = a.channels or CHANNELS
    OUT.mkdir(parents=True, exist_ok=True)
    reps = [channel_report(n, a.end) for n in names]
    (OUT / f"{a.end}.json").write_text(json.dumps(reps, ensure_ascii=False, indent=1), encoding="utf-8")
    write_md(reps, a.end, OUT / f"{a.end}.md")
    print(json.dumps({r["channel"]: {"data_through": r["data_through"],
                                     "videos": len(r["videos"])} for r in reps}, ensure_ascii=False))
    print(OUT / f"{a.end}.md")


if __name__ == "__main__":
    main()
