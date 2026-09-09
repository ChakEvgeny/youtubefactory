#!/usr/bin/env python3
"""Сканер языков и ниш YouTube Data API v3 с кэшем в Supabase.

Методология ранжирования и структура niche-analysis заимствованы у скиллов
yt-research / youtube-competitor-analyzer; сбор данных — свой, чтобы держать
ключ в .env и не жечь квоту повторными запросами.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import isodate
import yaml
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from langdetect import DetectorFactory, LangDetectException
from langdetect import detect as lang_detect
from supabase import create_client

DetectorFactory.seed = 0  # детерминированный langdetect

ROOT = Path(__file__).resolve().parent.parent
UNITS_SEARCH = 100
UNITS_LIST = 1
CACHE_TTL_DAYS = 7
MIN_DURATION_SEC = 180
YOUNG_CHANNEL_DAYS = 365
BIG_SUBS = 10_000
ANOMALY_RATIO = 3.0
MIN_SUBS_ANOMALY = 1000   # микроканалы дают ложные всплески view/sub
COMP_BAND_LO = 5    # оптимум насыщения копировщиками: 5..15 молодых каналов с >=10k
COMP_BAND_HI = 15
BATCH = 50
YTDLP_BIN = shutil.which("yt-dlp") or str(Path.home() / ".local/bin/yt-dlp")
YTDLP_RESULTS = 60        # ytsearch60 — бесплатно, поэтому берём с запасом
YTDLP_WORKERS = 3         # больше — ловим 429
YTDLP_PAUSE = (1.0, 2.0)  # пауза перед каждым запросом, сек


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    s = re.sub(r"\.(\d{6})\d+", r".\1", s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_fresh(ts, ttl_days: int = CACHE_TTL_DAYS) -> bool:
    dt = parse_ts(ts)
    return dt is not None and (utcnow() - dt) < timedelta(days=ttl_days)


def chunked(seq, size=BATCH):
    seq = list(seq)
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


# ── окно publishedAfter ────────────────────────────────────────────────────
# Привязываем окно к началу ISO-недели: иначе publishedAfter (и вместе с ним
# cache_key) менялся бы каждый день и 7-дневный кэш никогда бы не срабатывал.
def window_start(days: int, anchor: date | None = None) -> datetime:
    today = anchor or utcnow().date()
    monday = today - timedelta(days=today.weekday())
    return datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=days)


def make_cache_key(lang, region, niche, query, published_after, order_by,
                   video_duration="any", backend="api") -> str:
    # videoDuration и backend обязаны входить в ключ: один и тот же запрос через
    # api и через ytdlp даёт разную выдачу, иначе кэш вернёт чужой результат.
    raw = (f"{lang}|{region}|{niche}|{query}|{published_after.strftime('%Y-%m-%d')}"
           f"|{order_by}|{video_duration}|{backend}")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def ytdlp_search(query, lang, region, n=YTDLP_RESULTS, lang_hint=True, timeout=180):
    """Поиск через yt-dlp. Бесплатно, но без publishedAt — дату фильтруем позже."""
    cmd = [YTDLP_BIN, "--flat-playlist", "--dump-json", "--no-warnings", "--ignore-errors"]
    if lang_hint:
        cmd += ["--extractor-args", f"youtube:lang={lang}", "--geo-bypass-country", region]
    cmd.append(f"ytsearch{n}:{query}")
    time.sleep(random.uniform(*YTDLP_PAUSE))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    ids, meta = [], {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        vid = d.get("id")
        if not vid or vid in meta:
            continue
        ids.append(vid)
        meta[vid] = {"title": d.get("title"), "duration": d.get("duration"),
                     "view_count": d.get("view_count"), "channel_id": d.get("channel_id")}
    if not ids and proc.returncode != 0:
        raise RuntimeError((proc.stderr or "yt-dlp failed")[:200])
    return ids, meta


def competition_factor(competition: int) -> float:
    """Полоса насыщения: мало копировщиков — ниша ещё не доказана, много — уже тесно."""
    if competition < COMP_BAND_LO:
        return 0.5 + 0.1 * competition
    if competition > COMP_BAND_HI:
        return COMP_BAND_HI / competition
    return 1.0


class Budget:
    """Счётчик units. max=None — без лимита."""

    def __init__(self, max_units):
        self.max = max_units
        self.spent = 0

    def can(self, cost: int) -> bool:
        return self.max is None or (self.spent + cost) <= self.max

    def spend(self, cost: int):
        self.spent += cost

    @property
    def left(self):
        return None if self.max is None else self.max - self.spent


class Scanner:
    def __init__(self, sb, yt, cfg, budget, days, video_duration, verbose=True,
                 backend="ytdlp", lang_hint=True):
        self.sb = sb
        self.yt = yt
        self.cfg = cfg
        self.budget = budget
        self.days = days
        self.video_duration = video_duration
        self.verbose = verbose
        self.backend = backend
        self.lang_hint = lang_hint
        self.force_refresh = False
        self.published_after = window_start(days)
        self.exhausted = False
        # колонки relevance добавляются миграцией — работаем и без них
        self.has_relevant = self._probe("videos", "relevant")
        self.has_n_relevant = self._probe("niche_scores", "n_relevant")
        self.has_thumbnail = self._probe("videos", "thumbnail_url")
        self._warned_relevance = False

    def _probe(self, table, column):
        try:
            self.sb.table(table).select(column).limit(1).execute()
            return True
        except Exception:
            return False

    def log(self, msg):
        if self.verbose:
            print(msg, flush=True)

    # ── search.list (100 units) ────────────────────────────────────────────
    def cached_search(self, key):
        res = self.sb.table("searches").select("*").eq("cache_key", key).limit(1).execute()
        rows = res.data or []
        if rows and is_fresh(rows[0].get("created_at")):
            return rows[0]
        return None

    def _save_search(self, key, lang, region, niche, query, order_by, ids, units):
        self.sb.table("searches").upsert({
            "cache_key": key, "lang": lang, "region": region, "niche": niche,
            "query": query, "published_after": self.published_after.isoformat(),
            "order_by": order_by, "video_ids": ids, "units_spent": units,
            "created_at": utcnow().isoformat(),
        }, on_conflict="cache_key").execute()

    def _api_search(self, lang, region, query, order_by):
        params = dict(
            part="snippet", type="video", q=query, relevanceLanguage=lang,
            regionCode=region,
            publishedAfter=self.published_after.strftime("%Y-%m-%dT%H:%M:%SZ"),
            order=order_by, maxResults=BATCH,
        )
        if self.video_duration != "any":
            params["videoDuration"] = self.video_duration
        resp = self.yt.search().list(**params).execute()
        return [it["id"]["videoId"] for it in resp.get("items", [])
                if it.get("id", {}).get("videoId")]

    def search_batch(self, lang, region, niche, queries, order_by="viewCount"):
        """Все запросы пары разом. ytdlp — параллельно в 3 потока и бесплатно."""
        keys = {q: make_cache_key(lang, region, niche, q, self.published_after,
                                  order_by, self.video_duration, self.backend)
                for q in queries}
        res, misses, hits = {}, [], 0
        for q in queries:
            hit = self.cached_search(keys[q])
            if hit:
                res[q] = list(hit.get("video_ids") or [])
                hits += 1
            else:
                misses.append(q)

        if misses and self.backend == "ytdlp":
            with ThreadPoolExecutor(max_workers=YTDLP_WORKERS) as ex:
                futs = {ex.submit(ytdlp_search, q, lang, region, YTDLP_RESULTS,
                                  self.lang_hint): q for q in misses}
                for f in as_completed(futs):
                    q = futs[f]
                    try:
                        ids, _ = f.result()
                    except Exception as e:
                        self.log(f"    ! yt-dlp «{q}»: {str(e)[:90]}")
                        ids = []
                    res[q] = ids
                    self._save_search(keys[q], lang, region, niche, q, order_by, ids, 0)
        else:
            for q in misses:
                if not self.budget.can(UNITS_SEARCH):
                    self.exhausted = True
                    return None, hits, 0
                ids = self._api_search(lang, region, q, order_by)
                self.budget.spend(UNITS_SEARCH)
                res[q] = ids
                self._save_search(keys[q], lang, region, niche, q, order_by, ids, UNITS_SEARCH)

        ordered = []
        for q in queries:
            ordered.extend(res.get(q, []))
        return list(dict.fromkeys(ordered)), hits, len(misses)

    # ── videos.list (1 unit) ───────────────────────────────────────────────
    def ensure_videos(self, ids, lang, niche):
        known = {}
        for chunk in chunked(ids):
            res = self.sb.table("videos").select("*").in_("id", chunk).execute()
            for row in (res.data or []):
                known[row["id"]] = row

        stale = (list(ids) if self.force_refresh
                 else [i for i in ids if i not in known or not is_fresh(known[i].get("fetched_at"))])
        for chunk in chunked(stale):
            if not self.budget.can(UNITS_LIST):
                self.exhausted = True
                break
            resp = self.yt.videos().list(
                part="snippet,statistics,contentDetails", id=",".join(chunk), maxResults=BATCH
            ).execute()
            self.budget.spend(UNITS_LIST)
            rows = []
            for it in resp.get("items", []):
                sn = it.get("snippet", {})
                st = it.get("statistics", {})
                cd = it.get("contentDetails", {})
                try:
                    dur = int(isodate.parse_duration(cd.get("duration", "PT0S")).total_seconds())
                except Exception:
                    dur = 0
                title = sn.get("title") or ""
                desc = sn.get("description") or ""
                try:
                    detected = lang_detect(f"{title} {desc[:500]}".strip()) if title or desc else None
                except LangDetectException:
                    detected = None
                rows.append({
                    "id": it["id"],
                    "channel_id": sn.get("channelId"),
                    "title": title,
                    "description": desc[:2000],
                    "published_at": sn.get("publishedAt"),
                    "duration_sec": dur,
                    "view_count": int(st.get("viewCount", 0) or 0),
                    "like_count": int(st.get("likeCount", 0) or 0),
                    "comment_count": int(st.get("commentCount", 0) or 0),
                    "default_language": sn.get("defaultLanguage"),
                    "default_audio_language": sn.get("defaultAudioLanguage"),
                    "detected_lang": detected,
                    "lang": lang,
                    "niche": niche,
                    "fetched_at": utcnow().isoformat(),
                })
                if self.has_thumbnail:
                    thumbs = sn.get("thumbnails") or {}
                    best = thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}
                    rows[-1]["thumbnail_url"] = best.get("url")
            if rows:
                self.sb.table("videos").upsert(rows, on_conflict="id").execute()
                for r in rows:
                    known[r["id"]] = r
        return [known[i] for i in ids if i in known]

    # ── channels.list (1 unit) ─────────────────────────────────────────────
    def ensure_channels(self, ids):
        ids = [i for i in dict.fromkeys(ids) if i]
        known = {}
        for chunk in chunked(ids):
            res = self.sb.table("channels").select("*").in_("id", chunk).execute()
            for row in (res.data or []):
                known[row["id"]] = row

        stale = [i for i in ids if i not in known or not is_fresh(known[i].get("fetched_at"))]
        for chunk in chunked(stale):
            if not self.budget.can(UNITS_LIST):
                self.exhausted = True
                break
            resp = self.yt.channels().list(
                part="snippet,statistics", id=",".join(chunk), maxResults=BATCH
            ).execute()
            self.budget.spend(UNITS_LIST)
            rows = []
            for it in resp.get("items", []):
                sn = it.get("snippet", {})
                st = it.get("statistics", {})
                rows.append({
                    "id": it["id"],
                    "title": sn.get("title"),
                    "subscriber_count": int(st.get("subscriberCount", 0) or 0),
                    "video_count": int(st.get("videoCount", 0) or 0),
                    "view_count": int(st.get("viewCount", 0) or 0),
                    "created_at": sn.get("publishedAt"),
                    "country": sn.get("country"),
                    "fetched_at": utcnow().isoformat(),
                })
            if rows:
                self.sb.table("channels").upsert(rows, on_conflict="id").execute()
                for r in rows:
                    known[r["id"]] = r
        return known

    # ── одна пара язык x ниша ──────────────────────────────────────────────
    def scan_pair(self, lang, niche):
        langcfg = self.cfg["languages"][lang]
        region, rpm = langcfg["region"], float(langcfg["rpm_estimate"])
        nichecfg = self.cfg["niches"][niche]
        qmap = nichecfg.get("queries", {})
        if lang not in qmap:
            return "no_queries"
        queries = qmap[lang]
        nfactor = float(nichecfg.get("rpm_niche_factor", 1.0))

        video_ids, cache_hits, api_calls = self.search_batch(lang, region, niche, queries)
        if video_ids is None:
            return None

        vids = self.ensure_videos(video_ids, lang, niche)
        n_raw = len(vids)

        # ytdlp не отдаёт дату публикации, поэтому окно режем здесь, после videos.list
        fresh = [v for v in vids
                 if (parse_ts(v.get("published_at")) or self.published_after) >= self.published_after]
        dropped_old = n_raw - len(fresh)

        long_enough = [v for v in fresh if (v.get("duration_sec") or 0) >= MIN_DURATION_SEC]
        dropped_short = len(fresh) - len(long_enough)

        kept = []
        for v in long_enough:
            dal = (v.get("default_audio_language") or "").lower()
            if v.get("detected_lang") == lang or dal.startswith(lang):
                kept.append(v)
        dropped_lang = len(long_enough) - len(kept)

        chan_map = self.ensure_channels([v.get("channel_id") for v in kept])

        now = utcnow()
        # Метрики считаем только по relevant=1. Если разметки ещё нет —
        # честно считаем по всем выжившим и говорим об этом.
        if self.has_relevant and any(v.get("relevant") is not None for v in kept):
            scored = [v for v in kept if v.get("relevant") == 1]
            n_relevant = len(scored)
        else:
            scored, n_relevant = kept, None
            if kept and not self._warned_relevance:
                self.log("    ! relevance не проставлен — метрики по всем выжившим; "
                         "запусти scripts/relevance.py")
                self._warned_relevance = True

        demand_views = sum(int(v.get("view_count") or 0) for v in scored)
        scored_chans = {v.get("channel_id") for v in scored if v.get("channel_id")}
        young_ids, competition, anomalies, young_views = set(), 0, 0, 0
        for cid in scored_chans:
            ch = chan_map.get(cid) or {}
            created = parse_ts(ch.get("created_at"))
            if created and (now - created) < timedelta(days=YOUNG_CHANNEL_DAYS):
                young_ids.add(cid)
                if int(ch.get("subscriber_count") or 0) >= BIG_SUBS:
                    competition += 1
        for v in scored:
            ch = chan_map.get(v.get("channel_id")) or {}
            subs = int(ch.get("subscriber_count") or 0)
            views = int(v.get("view_count") or 0)
            if v.get("channel_id") in young_ids:
                young_views += views
            if subs >= MIN_SUBS_ANOMALY and views / subs >= ANOMALY_RATIO:
                anomalies += 1

        newcomer_share = (young_views / demand_views) if demand_views else 0.0
        cfactor = competition_factor(competition)
        score = rpm * nfactor * demand_views * cfactor * (1 + newcomer_share)

        top = sorted(scored, key=lambda v: int(v.get("view_count") or 0), reverse=True)[:10]
        details = {
            "queries": queries,
            "region": region,
            "published_after": self.published_after.strftime("%Y-%m-%d"),
            "video_duration": self.video_duration,
            "searches_from_cache": cache_hits,
            "searches_from_api": api_calls,
            "n_raw_videos": n_raw,
            "dropped_old": dropped_old,
            "dropped_short": dropped_short,
            "search_backend": self.backend,
            "dropped_lang": dropped_lang,
            "n_channels": len(chan_map),
            "n_young_channels": len(young_ids),
            "competition_factor": round(cfactor, 4),
            "rpm_niche_factor": nfactor,
            "n_relevant": n_relevant,
            "relevance_labeled": n_relevant is not None,
            "top_videos": [{
                "id": v["id"], "title": v.get("title"), "views": int(v.get("view_count") or 0),
                "channel": (chan_map.get(v.get("channel_id")) or {}).get("title"),
                "subs": int((chan_map.get(v.get("channel_id")) or {}).get("subscriber_count") or 0),
                "detected_lang": v.get("detected_lang"),
            } for v in top],
        }
        row = {
            "lang": lang, "niche": niche, "run_date": utcnow().date().isoformat(),
            "demand_views": demand_views, "n_videos": len(kept), "competition": competition,
            "newcomer_share": round(newcomer_share, 4), "anomalies": anomalies,
            "rpm_estimate": rpm, "score": round(score, 2), "details": details,
        }
        if self.has_n_relevant:
            row["n_relevant"] = n_relevant
        self.sb.table("niche_scores").upsert(row, on_conflict="lang,niche,run_date").execute()
        # в таблице niche_scores отдельной колонки нет — фактор живёт в details,
        # а в возвращаемый словарь кладём его уже после upsert, только для вывода
        row["competition_factor"] = round(cfactor, 4)
        row.setdefault("n_relevant", n_relevant)
        return row


# ── dry-run: план без единого вызова API ───────────────────────────────────
def plan(sb, cfg, langs, niches, days, video_duration, backend="api"):
    pa = window_start(days)
    need_api, from_cache, rows = 0, 0, []
    for niche in niches:
        for lang in langs:
            region = cfg["languages"][lang]["region"]
            for q in cfg["niches"][niche].get("queries", {}).get(lang, []):
                key = make_cache_key(lang, region, niche, q, pa, "viewCount",
                                     video_duration, backend)
                if sb is None:  # нет доступа к Supabase — считаем кэш холодным
                    hit = False
                else:
                    res = sb.table("searches").select("created_at").eq("cache_key", key).limit(1).execute()
                    hit = bool(res.data) and is_fresh(res.data[0].get("created_at"))
                from_cache += int(hit)
                need_api += int(not hit)
                rows.append((lang, niche, q, "CACHE" if hit else "API"))
    n_pairs = len(langs) * len(niches)
    search_units = need_api * UNITS_SEARCH
    # worst case: 2 запроса x 50 видео = 100 видео -> 2 вызова videos.list;
    # до 100 уникальных каналов -> 2 вызова channels.list
    list_units_max = n_pairs * 4 * UNITS_LIST
    return {
        "rows": rows, "pairs": n_pairs, "queries": len(rows),
        "from_cache": from_cache, "need_api": need_api,
        "search_units": search_units, "list_units_max": list_units_max,
        "total_max": search_units + list_units_max,
        "published_after": pa.strftime("%Y-%m-%d"), "video_duration": video_duration,
    }


def print_table(rows):
    hdr = (f"{'lang':<5} {'niche':<22} {'demand_views':>13} {'n_vid':>6} {'n_rel':>6} {'comp':>5} "
           f"{'cfac':>6} {'newc':>6} {'anom':>5} {'score':>16}")
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in sorted(rows, key=lambda x: x["score"], reverse=True):
        nrel = r.get('n_relevant')
        print(f"{r['lang']:<5} {r['niche']:<22} {r['demand_views']:>13,} {r['n_videos']:>6} "
              f"{('-' if nrel is None else nrel):>6} "
              f"{r['competition']:>5} {r['competition_factor']:>6.2f} {r['newcomer_share']:>6.2f} "
              f"{r['anomalies']:>5} {r['score']:>16,.0f}")


def write_report(rows, budget, days, video_duration, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Scan {utcnow().date().isoformat()}", "",
        f"- Окно: последние {days} дней (publishedAfter = {window_start(days).strftime('%Y-%m-%d')})",
        f"- videoDuration: `{video_duration}`, минимальная длительность {MIN_DURATION_SEC} сек",
        f"- Потрачено units: **{budget.spent}**" + (f" из {budget.max}" if budget.max else ""),
        "",
        "| lang | niche | demand_views | n_videos | n_relevant | competition | comp_factor | newcomer_share | anomalies | rpm | score |",
        "|------|-------|-------------:|---------:|-----------:|------------:|------------:|---------------:|----------:|----:|------:|",
    ]
    for r in sorted(rows, key=lambda x: x["score"], reverse=True):
        lines.append(f"| {r['lang']} | {r['niche']} | {r['demand_views']:,} | {r['n_videos']} | "
                     f"{'-' if r.get('n_relevant') is None else r['n_relevant']} | "
                     f"{r['competition']} | {r['competition_factor']:.2f} | "
                     f"{r['newcomer_share']:.2f} | {r['anomalies']} | "
                     f"{r['rpm_estimate']} | {r['score']:,.0f} |")
    for r in sorted(rows, key=lambda x: x["score"], reverse=True):
        d = r["details"]
        lines += ["", f"## {r['lang']} / {r['niche']}", "",
                  f"Запросы: {', '.join(repr(q) for q in d['queries'])}",
                  f"Сырых видео {d['n_raw_videos']}, отсеяно коротких {d['dropped_short']}, "
                  f"отсеяно языковым фильтром {d['dropped_lang']}, осталось {r['n_videos']}.", ""]
        if d["top_videos"]:
            lines += ["| views | subs | lang | channel | title |", "|------:|-----:|:----:|---------|-------|"]
            for v in d["top_videos"]:
                t = (v["title"] or "").replace("|", "\\|")[:70]
                lines.append(f"| {v['views']:,} | {v['subs']:,} | {v['detected_lang']} | "
                             f"{(v['channel'] or '').replace('|', '')[:28]} | {t} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser(description="Сканер языков и ниш YouTube с кэшем в Supabase")
    ap.add_argument("--langs", help="через запятую, напр. de,en")
    ap.add_argument("--niches", help="через запятую")
    ap.add_argument("--max-units", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--video-duration", default="medium",
                    choices=["any", "medium", "long", "short"])
    ap.add_argument("--search-backend", default="ytdlp", choices=["ytdlp", "api"])
    ap.add_argument("--lang-hint", action=argparse.BooleanOptionalAction, default=True,
                    help="yt-dlp: youtube:lang=<lang> + --geo-bypass-country <region>")
    ap.add_argument("--refresh-videos", action="store_true",
                    help="перезапросить videos.list, игнорируя 7-дневный кэш")
    ap.add_argument("--config", default=str(ROOT / "config" / "niches.yaml"))
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    langs = [x.strip() for x in args.langs.split(",")] if args.langs else list(cfg["languages"])
    niches = [x.strip() for x in args.niches.split(",")] if args.niches else list(cfg["niches"])
    for l in langs:
        if l not in cfg["languages"]:
            sys.exit(f"Неизвестный язык: {l}")
    for n in niches:
        if n not in cfg["niches"]:
            sys.exit(f"Неизвестная ниша: {n}")

    load_dotenv(ROOT / ".env")
    have_sb = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY"))

    if args.dry_run:
        sb = (create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
              if have_sb else None)
        if sb is None:
            print("! SUPABASE_URL / SUPABASE_SERVICE_KEY пусты в .env — план считается\n"
                  "  по холодному кэшу, то есть это верхняя граница расхода.\n")
        p = plan(sb, cfg, langs, niches, args.days, args.video_duration,
                 args.search_backend)
        print(f"DRY-RUN: {len(langs)} яз. x {len(niches)} ниш = {p['pairs']} пар, {p['queries']} запросов")
        print(f"  publishedAfter = {p['published_after']}  videoDuration = {p['video_duration']}")
        print(f"  из кэша (моложе {CACHE_TTL_DAYS} дн.): {p['from_cache']}   пойдут в API: {p['need_api']}")
        print(f"  search.list: {p['need_api']} x {UNITS_SEARCH} = {p['search_units']} units")
        print(f"  videos/channels.list (макс.): {p['list_units_max']} units")
        print(f"  ИТОГО максимум: {p['total_max']} units из 10000/день "
              f"({p['total_max'] / 100:.1f}% дневной квоты)")
        if args.max_units is not None:
            print(f"  --max-units {args.max_units}: "
                  + ("хватит" if p["total_max"] <= args.max_units else "НЕ хватит, прогон остановится досрочно"))
        return

    missing = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "YOUTUBE_API_KEY") if not os.getenv(k)]
    if missing:
        sys.exit("Нет значений в .env для: " + ", ".join(missing))  # печатаем только имена
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))

    yt = build("youtube", "v3", developerKey=os.getenv("YOUTUBE_API_KEY"), cache_discovery=False)
    budget = Budget(args.max_units)
    sc = Scanner(sb, yt, cfg, budget, args.days, args.video_duration,
                 backend=args.search_backend, lang_hint=args.lang_hint)
    sc.force_refresh = args.refresh_videos

    pairs = [(l, n) for n in niches for l in langs]
    results, done = [], 0
    for lang, niche in pairs:
        if sc.exhausted:
            break
        sc.log(f"→ {lang}/{niche} … (потрачено {budget.spent} units)")
        try:
            row = sc.scan_pair(lang, niche)
        except HttpError as e:
            reason = getattr(e, "reason", "") or str(e)[:200]
            print(f"  ! HttpError: {reason}", file=sys.stderr)
            if "quota" in str(e).lower():
                sc.exhausted = True
                break
            continue
        if row == "no_queries":
            sc.log(f"  пропуск: для {lang} в нише {niche} запросы не заданы")
            done += 1
            continue
        if row is None:
            break
        results.append(row)
        done += 1
        sc.log(f"  видео {row['n_videos']}, просмотры {row['demand_views']:,}, score {row['score']:,.0f}")

    if results:
        print_table(results)
    remaining = len(pairs) - done
    print(f"\nПотрачено units: {budget.spent}" + (f" из {budget.max}" if budget.max else ""))
    if sc.exhausted or remaining > 0:
        print(f"ОСТАНОВЛЕНО: бюджет units исчерпан. Осталось необработанных пар: {remaining}")
        print("Прогресс сохранён в Supabase — повтор с тем же --max-units продолжит с кэша.")
    if results:
        p = write_report(results, budget, args.days, args.video_duration,
                         ROOT / "reports" / f"scan_{utcnow().date().isoformat()}.md")
        print(f"Отчёт: {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
