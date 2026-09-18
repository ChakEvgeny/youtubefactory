#!/usr/bin/env python3
"""Разведка поля объясняющих каналов формата Why&How.

Зачем: перед тем как вкладываться в канал, надо знать, сколько таких уже есть,
кто из них вырос, кто нет, и чем выросшие отличаются. Поиск — через yt-dlp
(бесплатно), статистика каналов — через Data API `channels.list` по 1 unit.
`search.list` за 100 units не используем (правило из CLAUDE.md).

  python scripts/rivals_explain.py --out reports/rivals_explain.json
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import urllib.parse, urllib.request

# Запросы подобраны так, чтобы поймать формат, а не тему: и прямые названия
# рубрики, и типовые заголовки, на которых такие каналы живут.
QUERIES = [
    "why and how explained", "why you can't", "why can't humans",
    "how does it actually work explained", "why does your body",
    "science explainer animated", "animated explainer channel",
    "why is it impossible to", "how do submarines work",
    "why can't you drink seawater", "what happens if you",
    "the real reason why", "explained in 5 minutes science",
    "hand drawn science explainer", "why do we",
]

FMT = "%(channel_id)s|%(channel)s|%(view_count)s|%(duration)s|%(title)s"


def search(q: str, n: int = 20) -> list[dict]:
    try:
        out = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--print", FMT, f"ytsearch{n}:{q}"],
            capture_output=True, text=True, timeout=180).stdout
    except Exception as e:
        print(f"  ! {q}: {type(e).__name__}", flush=True)
        return []
    rows = []
    for line in out.splitlines():
        p = line.strip().split("|", 4)
        if len(p) < 5 or not p[0].startswith("UC"):
            continue
        try:
            rows.append({"cid": p[0], "chan": p[1], "views": int(p[2]),
                         "dur": int(float(p[3])), "title": p[4]})
        except ValueError:
            continue
    return rows


def api(path: str, **params) -> dict:
    key = os.getenv("YOUTUBE_API_KEY") or os.getenv("YT_API_KEY")
    if not key:
        raise RuntimeError("нет YOUTUBE_API_KEY в .env")
    params["key"] = key
    u = f"https://www.googleapis.com/youtube/v3/{path}?" + urllib.parse.urlencode(params)
    return json.loads(urllib.request.urlopen(u, timeout=40).read())


def channels(ids: list[str]) -> list[dict]:
    """channels.list — 1 unit на запрос, до 50 id за раз."""
    out = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        r = api("channels", part="snippet,statistics,contentDetails", id=",".join(chunk))
        out.extend(r.get("items", []))
        time.sleep(0.2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/rivals_explain.json")
    ap.add_argument("--per", type=int, default=20)
    a = ap.parse_args()

    seen: dict[str, dict] = {}
    for q in QUERIES:
        rows = search(q, a.per)
        for r in rows:
            c = seen.setdefault(r["cid"], {"cid": r["cid"], "chan": r["chan"],
                                           "hits": 0, "vids": []})
            c["hits"] += 1
            c["vids"].append({"views": r["views"], "dur": r["dur"], "title": r["title"]})
        print(f"  {q[:38]:38} каналов всего {len(seen)}", flush=True)

    print(f"\nуникальных каналов: {len(seen)}; тянем статистику…", flush=True)
    stats = channels(list(seen))
    for it in stats:
        c = seen.get(it["id"])
        if not c:
            continue
        sn, st = it["snippet"], it["statistics"]
        c["title"] = sn.get("title")
        c["published"] = sn.get("publishedAt", "")[:10]
        c["country"] = sn.get("country", "")
        c["desc"] = (sn.get("description") or "").replace("\n", " ")[:400]
        c["subs"] = int(st.get("subscriberCount", 0)) if not st.get("hiddenSubscriberCount") else None
        c["views"] = int(st.get("viewCount", 0))
        c["count"] = int(st.get("videoCount", 0))

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    rows = [v for v in seen.values() if "subs" in v]
    Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"записано {len(rows)} каналов -> {a.out}")


if __name__ == "__main__":
    main()
