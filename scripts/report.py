#!/usr/bin/env python3
"""Сводный отчёт по прогону: reports/niche_scan_<дата>.md.

Читает niche_scores + videos + channels из Supabase. Работает и без разметки
relevance/format — тогда соответствующие колонки помечены как «нет данных».
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
YOUNG_DAYS = 365
MIN_SUBS_ANOMALY = 1000
ANOMALY_RATIO = 3.0
MIN_DURATION_SEC = 180
RAW_THRESHOLD = 25

# Разбор топ-5 пишется руками по итогам цифр — это суждение, не расчёт.
NARRATIVE = {
    "industries_inside": (
        "Держит первое место и после отсева мусора: 68 из 82 роликов (82%) реально про "
        "отрасль. competition = 7 — в оптимальной полосе, 58% просмотров у каналов моложе "
        "года, 24 из 41 аномалии на молодых каналах. Единственная ниша в топе, где "
        "максимальный спрос сочетается с реальной проходимостью для новичка.",
        "Производство. Порты, склады и заводы нечем снять со стока Pexels/Pixabay, а "
        "AI-кадры плохо держат промышленную геометрию. Себестоимость ролика будет выше, "
        "чем в нишах, где хватает говорящей головы или слайдов."),
    "true_crime_docs": (
        "Самая чистая выдача из топ-5 — 66 из 77 роликов (85%) по делу, то есть запросы "
        "попадают в тему почти без промаха. competition = 4: копировщиками не забита.",
        "newcomer_share 0.06 — почти весь трафик у устоявшихся каналов, хотя 9 из 18 "
        "аномалий всё же у молодых. Пробиться можно, но медленно. Отдельно — модерация: "
        "детали преступлений упираются в ограничения рекламодателей."),
    "business_breakdowns": (
        "Самый большой пул роликов (155 прошли фильтры, 99 релевантных) и competition = 8 — "
        "верхняя граница оптимальной полосы. rpm_niche_factor 1.0: самая дорогая реклама "
        "наравне с деньгами и технологиями.",
        "37% выдачи — мусор: биржевая аналитика и мотивация лезут на те же запросы. И лишь "
        "7 из 29 аномалий на молодых каналах. Ниша зрелая: место есть, но новичка пускает "
        "неохотно."),
    "military_history": (
        "Лучшая проходимость в топ-5: 12 из 18 аномалий — каналы моложе 12 месяцев. Если "
        "цель войти с нуля, это самый мягкий вход среди крупных ниш.",
        "Точность запросов 43% — худшая в топе, больше половины выдачи не по теме; после "
        "отсева score упал с 325M до 122M. Запросы придётся переписывать. Плюс военный "
        "контент традиционно ловит ограничения рекламодателей, так что фактический RPM "
        "может оказаться ниже расчётного 0.7."),
    "geography_maps": (
        "Ровная ниша без перекосов: точность 68%, competition = 4, шесть из десяти аномалий "
        "у молодых каналов. Формат хорошо ложится на наш конвейер — карты и схемы "
        "собираются без съёмки.",
        "Аномалий всего 10 при newcomer_share 0.10: случаев «выстрелил с нуля» мало, рост "
        "будет медленным. rpm_niche_factor 0.7 дополнительно срезает деньги."),
}


def parse_ts(v):
    if not v: return None
    dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fetch_all(sb, table, cols="*", page=1000):
    out, off = [], 0
    while True:
        b = sb.table(table).select(cols).range(off, off + page - 1).execute().data
        if not b: break
        out += b
        if len(b) < page: break
        off += page
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", default="en,de")
    args = ap.parse_args()
    langs = [x.strip() for x in args.langs.split(",")]

    cfg = yaml.safe_load((ROOT / "config" / "niches.yaml").read_text(encoding="utf-8"))
    load_dotenv(ROOT / ".env")
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
    now = datetime.now(timezone.utc)

    excluded = {n: c.get("excluded_reason", "")
                for n, c in cfg["niches"].items() if c.get("excluded")}
    scores = [r for r in (sb.table("niche_scores").select("*").execute().data or [])
              if r["niche"] not in excluded]
    by = {(r["lang"], r["niche"]): r for r in scores}
    total = collections.defaultdict(float)
    for r in scores:
        if r["lang"] in langs:
            total[r["niche"]] += r["score"] or 0

    vcols = "id,channel_id,view_count,lang,niche,duration_sec,detected_lang,default_audio_language"
    has_fmt = True
    try:
        sb.table("videos").select("format").limit(1).execute()
        vcols += ",format,relevant"
    except Exception:
        has_fmt = False
    vids = fetch_all(sb, "videos", vcols)
    chs = {c["id"]: c for c in fetch_all(sb, "channels", "id,subscriber_count,created_at,title")}

    def survivors(lang, niche):
        out = []
        for v in vids:
            if v["lang"] != lang or v["niche"] != niche: continue
            if (v.get("duration_sec") or 0) < MIN_DURATION_SEC: continue
            dal = (v.get("default_audio_language") or "").lower()
            if v.get("detected_lang") == lang or dal.startswith(lang):
                out.append(v)
        return out

    # аномалии и возраст каналов
    anom = {}
    for niche in cfg["niches"]:
        for lang in langs:
            a = y = 0
            for v in survivors(lang, niche):
                ch = chs.get(v.get("channel_id"))
                if not ch: continue
                subs = ch.get("subscriber_count") or 0
                if subs < MIN_SUBS_ANOMALY: continue
                if (v.get("view_count") or 0) / subs < ANOMALY_RATIO: continue
                a += 1
                cr = parse_ts(ch.get("created_at"))
                if cr and (now - cr) < timedelta(days=YOUNG_DAYS): y += 1
            anom[(lang, niche)] = (a, y)

    # запросы ниже порога
    low = collections.defaultdict(list)
    cur = {(l, n, q) for n in cfg["niches"] for l in langs
           for q in cfg["niches"][n].get("queries", {}).get(l, [])}
    # в searches могут лежать дубли одного запроса под разными cache_key
    # (смена схемы ключа / другой бэкенд) — берём максимум по запросу
    best = {}
    for r in fetch_all(sb, "searches", "lang,niche,query,video_ids"):
        k = (r["lang"], r["niche"], r["query"])
        if k in cur:
            n = len(r["video_ids"] or [])
            best[k] = max(best.get(k, 0), n)
    for (lang, niche, query), n in best.items():
        if n < RAW_THRESHOLD:
            low[(lang, niche)].append((query, n))

    order = sorted(total.items(), key=lambda x: -x[1])
    excl_note = ([f"> **Исключены из рассмотрения:** "
                  + "; ".join(f"`{n}` — {r.strip()}" for n, r in excluded.items()), ""]
                 if excluded else [])
    L = [f"# Сканирование ниш — {now.date().isoformat()}", "",
         f"Языки: {', '.join(langs)}. Ниш: {len(cfg['niches'])}. "
         f"Окно 90 дней, videoDuration=medium, минимум {MIN_DURATION_SEC} сек.",
         f"Сортировка по сумме score {'+'.join(l.upper() for l in langs)}.", ""]
    L += excl_note
    if not has_fmt:
        L += ["> **Разметка не выполнена.** Колонок `videos.relevant` / `videos.format` / ",
              "> `niche_scores.n_relevant` нет в базе — `n_rel` и «доминирующий формат» "
              "пусты.", "> Применить `supabase/migration_relevance.sql`, затем "
              "`scripts/relevance.py`.", ""]

    L += ["## Ниша × язык", "",
          "| ниша | яз | demand_views | n_vid | n_rel | comp | cfac | newc | anom | score |",
          "|------|----|-------------:|------:|------:|-----:|-----:|-----:|-----:|------:|"]
    for niche, _ in order:
        for lang in langs:
            r = by.get((lang, niche))
            if not r:
                continue
            d = r.get("details") or {}
            nrel = r.get("n_relevant", d.get("n_relevant"))
            L.append(f"| {niche} | {lang} | {r['demand_views']:,} | {r['n_videos']} | "
                     f"{'—' if nrel is None else nrel} | {r['competition']} | "
                     f"{d.get('competition_factor', 0):.2f} | {r['newcomer_share']:.2f} | "
                     f"{r['anomalies']} | {r['score']:,.0f} |")

    L += ["", "## По нишам: формат, новички, объём выдачи", "",
          "| ниша | сумма score | доминирующий формат | доля новичков (newc) | запросы <25 сырых |",
          "|------|------------:|---------------------|---------------------:|-------------------|"]
    for niche, s in order:
        fmts = collections.Counter()
        if has_fmt:
            for lang in langs:
                for v in survivors(lang, niche):
                    if v.get("relevant") == 1 and v.get("format"):
                        fmts[v["format"]] += 1
        if fmts:
            top, cnt = fmts.most_common(1)[0]
            fmt_s = f"{top} ({cnt * 100 // sum(fmts.values())}%)"
        else:
            fmt_s = "— нет разметки —"
        newc = [f"{lang}:{by[(lang, niche)]['newcomer_share']:.2f}"
                for lang in langs if (lang, niche) in by]
        lows = [f"{lang} «{q}»={c}" for lang in langs for q, c in low.get((lang, niche), [])]
        L.append(f"| {niche} | {s:,.0f} | {fmt_s} | {', '.join(newc)} | "
                 f"{'; '.join(lows) if lows else '—'} |")

    L += ["", "## Пускают ли новичков: молодые каналы среди аномалий", "",
          "Аномалия = ролик с view/sub ≥ 3 у канала от 1000 подписчиков. "
          "Доля молодых показывает, попадают ли в выброс каналы моложе 12 месяцев.", "",
          "| ниша | яз | аномалий | из них моложе 12 мес | доля |",
          "|------|----|---------:|---------------------:|-----:|"]
    ranked = sorted(((k, v) for k, v in anom.items() if v[0]),
                    key=lambda x: (-x[1][1], -(x[1][1] / x[1][0])))
    for (lang, niche), (a, y) in ranked[:12]:
        L.append(f"| {niche} | {lang} | {a} | {y} | {y / a * 100:.0f}% |")

    # ── каналы-цели по топ-5 нишам EN ───────────────────────────────────
    L += ["", "## Каналы-цели: топ-5 ниш, язык EN", "",
          "Кто уже пробился в нише за последние 90 дней. Отбор: каналы с "
          "релевантными роликами, приоритет — молодым (до 12 мес) и тем, у кого "
          "ролик обогнал подписную базу (v/s = просмотры / подписчики).", ""]
    for niche, _ in order[:5]:
        agg = {}
        for v in survivors("en", niche):
            if has_fmt and v.get("relevant") != 1:
                continue
            cid = v.get("channel_id")
            ch = chs.get(cid)
            if not ch:
                continue
            a = agg.setdefault(cid, {"title": ch.get("title"), "subs": ch.get("subscriber_count") or 0,
                                     "created": parse_ts(ch.get("created_at")), "n": 0,
                                     "views": 0, "best_vs": 0.0, "fmt": collections.Counter()})
            a["n"] += 1
            a["views"] += int(v.get("view_count") or 0)
            if a["subs"]:
                a["best_vs"] = max(a["best_vs"], (v.get("view_count") or 0) / a["subs"])
            if v.get("format"):
                a["fmt"][v["format"]] += 1
        def age_m(c):
            return None if not c else round((now - c).days / 30.44, 1)
        ranked_ch = sorted(
            agg.values(),
            key=lambda a: (-(1 if a["created"] and (now - a["created"]) < timedelta(days=YOUNG_DAYS) else 0),
                           -a["best_vs"], -a["views"]))[:8]
        L += [f"### {niche}", "",
              "| канал | подписчики | возраст, мес | роликов | сумма просмотров | лучший v/s | формат |",
              "|-------|-----------:|-------------:|--------:|-----------------:|-----------:|--------|"]
        for a in ranked_ch:
            fm = a["fmt"].most_common(1)[0][0] if a["fmt"] else "—"
            am = age_m(a["created"])
            L.append(f"| {(a['title'] or '')[:34]} | {a['subs']:,} | "
                     f"{'—' if am is None else am} | {a['n']} | {a['views']:,} | "
                     f"{a['best_vs']:.1f} | {fm} |")
        L.append("")

    L += ["", "## Топ-5 ниш", ""]
    for i, (niche, s) in enumerate(order[:5], 1):
        why, risk = NARRATIVE.get(niche, ("—", "—"))
        L += [f"### {i}. {niche} — score {s:,.0f}", "",
              f"**Почему:** {why}", "", f"**Риск:** {risk}", ""]

    L += ["## Топ-3 языка по сумме score", "",
          "| язык | сумма score | ниш с данными |", "|------|------------:|--------------:|"]
    lang_tot = collections.defaultdict(float)
    lang_cnt = collections.Counter()
    for r in scores:
        if r["lang"] in langs:
            lang_tot[r["lang"]] += r["score"] or 0
            if r["n_videos"]: lang_cnt[r["lang"]] += 1
    for lang, s in sorted(lang_tot.items(), key=lambda x: -x[1])[:3]:
        L.append(f"| {lang} | {s:,.0f} | {lang_cnt[lang]} |")

    out = ROOT / "reports" / f"niche_scan_{now.date().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Отчёт: {out.relative_to(ROOT)}  ({len(L)} строк)")


if __name__ == "__main__":
    main()
