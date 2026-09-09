#!/usr/bin/env python3
import re
"""Сборка reports/deepdive_<дата>.md из собранных JSON."""
import collections, json, statistics, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SC = Path(sys.argv[1])
now = datetime.now(timezone.utc)
PRES = (sys.argv[2].split(",") if len(sys.argv) > 2 else ["dd"])
D, L, H, P, T = {}, {}, {"hooks": {}, "safety": {}}, {}, {}
for pre in PRES:
    D.update(json.loads((SC / f"{pre}_data.json").read_text(encoding="utf-8")))
    L.update(json.loads((SC / f"{pre}_llm.json").read_text(encoding="utf-8")))
    h = json.loads((SC / f"{pre}_hooks.json").read_text(encoding="utf-8"))
    H["hooks"].update(h.get("hooks", {})); H["safety"].update(h.get("safety", {}))
    P.update(json.loads((SC / f"{pre}_playlists.json").read_text(encoding="utf-8")))
    T.update(json.loads((SC / f"{pre}_topics.json").read_text(encoding="utf-8")))

TITLES = {"space_science": "space_science — космос и наука",
          "business_breakdowns": "business_breakdowns — разбор бизнеса",
          "geography_maps": "geography_maps — география и карты",
          "disasters_survival": "disasters_survival — катастрофы и выживание"}
def mmss(s):
    s = int(s or 0); return f"{s//60}:{s%60:02d}"
def yt(v): return f"https://youtu.be/{v}"

out = [f"# Глубокий разбор ниш (EN) — {now.date().isoformat()}", "",
       "Источник: Supabase (окно 90 дней, relevant=1) + yt-dlp. YouTube Data API не использован.",
       "Языковой фильтр ужесточён: latin ratio ≥ 90%, default_audio_language пуст или en, "
       "langdetect по title+описанию. Утечки помечены relevant=0 / lang_leak.", "",
       "> **`industries_inside` исключена** из разбора и очереди тем: ad-unfriendly "
       "(волна клонов «Inside the White Brahman Bull Horn Factory» — 68% просмотров ниши, "
       "забой и разделка скота, обложки unsafe) плюс значительная доля сфабрикованных "
       "AI-«заводов». Разбор ниши сохранён в истории отчётов от 2026-09-09.", ""]

# сводка по ad-safety сразу наверх
saf = H.get("safety", {})
if saf:
    out += ["## ⚠️ Проверка на ad-unfriendly", ""]
    for name, s in saf.items():
        out.append(f"- **{name}** — вердикт `{s.get('verdict')}`: {s.get('reason','')}")
        for e in (s.get("evidence") or [])[:3]:
            out.append(f"  - {e}")
    out.append("")

for niche, d in D.items():
    llm, hk = L[niche], H["hooks"][niche]
    idx = {v["id"]: v for v in d["top_views"] + d["top_vs"]}
    out += [f"---", "", f"# {TITLES.get(niche, niche)}", "",
            f"Релевантных роликов за 90 дней: **{d['n_relevant']}**.", ""]

    # 1. топы
    out += ["## Топ-30 по просмотрам", "",
            "| просмотры | канал | возраст канала | длит. | формат | заголовок |",
            "|----------:|-------|---------------:|------:|--------|-----------|"]
    for v in d["top_views"]:
        out.append(f"| {v['views']:,} | {(v['channel'] or '')[:24]} | "
                   f"{v['ch_age_m']} мес | {mmss(v['duration'])} | {v['format'] or '—'} | "
                   f"[{(v['title'] or '')[:62]}]({yt(v['id'])}) |")
    out += ["", "## Топ-15 по v/s (аномалии)", "",
            "| v/s | просмотры | подписчики | канал | возраст | заголовок |",
            "|----:|----------:|-----------:|-------|--------:|-----------|"]
    for v in d["top_vs"]:
        out.append(f"| {v['vs']} | {v['views']:,} | {v['subs']:,} | {(v['channel'] or '')[:22]} | "
                   f"{v['ch_age_m']} мес | [{(v['title'] or '')[:56]}]({yt(v['id'])}) |")

    # 2. субниши
    cl = llm["clusters"]; names = {c["id"]: c for c in cl["clusters"]}
    views = collections.defaultdict(int); cnt = collections.Counter(); young = collections.Counter()
    ex = collections.defaultdict(list)
    for vid, c in cl["assign"].items():
        v = idx.get(vid)
        if not v: continue
        views[c] += v["views"]; cnt[c] += 1
        if (v["ch_age_m"] or 99) < 12 and (v["vs"] or 0) >= 3: young[c] += 1
        ex[c].append(v)
    tot = sum(views.values()) or 1
    out += ["", "## Субниши", "",
            "| субниша | роликов | доля просмотров | аномалий у молодых | пример |",
            "|---------|--------:|----------------:|-------------------:|--------|"]
    for c in sorted(views, key=lambda x: -views[x]):
        top = max(ex[c], key=lambda v: v["views"])
        out.append(f"| **{names[c]['name']}** — {names[c].get('what','')[:60]} | {cnt[c]} | "
                   f"{views[c]*100//tot}% | {young[c]} | [{(top['title'] or '')[:44]}]({yt(top['id'])}) |")
    # субниши, забракованные проверкой на ad-unfriendly, точкой входа быть не могут
    UNSAFE_KW = ("рог", "брахман", "кож", "забой", "живот", "мяс")
    unsafe = {c for c in views
              if any(k in (names[c]["name"] + names[c].get("what", "")).lower() for k in UNSAFE_KW)}
    ranked_c = sorted(views, key=lambda x: (-young[x], -views[x]))
    safe_rank = [c for c in ranked_c if c not in unsafe]
    if unsafe:
        top_unsafe = ranked_c[0] if ranked_c[0] in unsafe else sorted(unsafe, key=lambda x: -views[x])[0]
        out += ["", f"> **Исключено из рекомендаций:** «{names[top_unsafe]['name']}» — "
                f"{views[top_unsafe]*100//tot}% просмотров ниши и {young[top_unsafe]} аномалий "
                "у молодых каналов, но проверка обложек и заголовков дала вердикт "
                "ad-unfriendly (забой и разделка животных). Формально это лучшая точка входа "
                "по цифрам, фактически — нет.", ""]
    entry = (safe_rank or ranked_c)[0]
    out += ["", f"**Точка входа:** {names[entry]['name']} — {young[entry]} аномалий "
            f"у каналов моложе 12 месяцев при {views[entry]*100//tot}% просмотров ниши.", ""]

    # 3. шаблоны заголовков
    tp = llm["templates"]; tnames = {t["id"]: t for t in tp["templates"]}
    tv = collections.defaultdict(list)
    for vid, t in tp["assign"].items():
        v = idx.get(vid)
        if v and t in tnames: tv[t].append(v["views"])
    out += ["## Шаблоны заголовков (топ-30)", "",
            "| шаблон | маска | частота | средние просмотры |",
            "|--------|-------|--------:|------------------:|"]
    for t in sorted(tv, key=lambda x: -len(tv[x])):
        out.append(f"| {tnames[t]['name']} | `{tnames[t].get('mask','')[:44]}` | "
                   f"{len(tv[t])} | {int(statistics.mean(tv[t])):,} |")

    # 4. обложки
    th = llm["thumbs"]
    out += ["", "## Обложки топ-15", "",
            "| объект | текст | цвета | лицо |", "|--------|-------|-------|------|"]
    for vid, t in list(th.items())[:15]:
        out.append(f"| {t.get('object','')[:34]} | {str(t.get('text',''))[:30]} | "
                   f"{t.get('colors','')[:26]} | {t.get('face','')} |")
    faces = sum(1 for t in th.values() if str(t.get("face", "")).lower().startswith("да"))
    texts = sum(1 for t in th.values() if str(t.get("text", "")).lower() not in ("нет", "no", ""))
    cols = collections.Counter()
    for t in th.values():
        for c in re.split(r"[,/]", str(t.get("colors", ""))):
            c = c.strip().lower()
            if c: cols[c] += 1
    out += ["", "**Три повторяющихся паттерна:**", "",
            f"1. Крупный текст на обложке — у {texts} из {len(th)}: заголовок дублируется прямо на картинке.",
            f"2. Лицо крупным планом — только у {faces} из {len(th)}: ниша не требует человека в кадре.",
            f"3. Доминирующая палитра — {', '.join(c for c, _ in cols.most_common(3))}.", ""]

    # 5. хуки
    out += ["## Хуки: первые 60 секунд", ""]
    if hk["n_subs"] < 4:
        out.append(f"> Субтитры удалось снять только с {hk['n_subs']} роликов — "
                   "у большинства топовых роликов ниши автосубтитры отключены. "
                   "Выборка нерепрезентативна, выводы ниже — гипотеза, а не факт.")
        out.append("")
    for h in hk["hooks"]:
        out += [f"- **{h.get('name')}** — {h.get('what','')}",
                f"  > «{(h.get('quote') or '')[:200]}»"]
    out.append("")

    # 6. длина и темп
    durs = [v["duration"] for v in d["top_views"] if v["duration"]]
    buckets = collections.Counter()
    for s in durs:
        buckets["<5 мин" if s < 300 else "5–10" if s < 600 else "10–20" if s < 1200 else ">20 мин"] += 1
    out += ["## Длина и темп публикаций", "",
            f"Медиана топ-30: **{mmss(statistics.median(durs))}**. Распределение: "
            + ", ".join(f"{k} — {v}" for k, v in buckets.items()) + ".", "",
            "| канал | подписчики | возраст | роликов за окно | темп, роликов/нед |",
            "|-------|-----------:|--------:|----------------:|------------------:|"]
    for t in d["targets"]:
        pdata = P.get(niche, {}).get(t["channel_id"], {})
        items, od = pdata.get("items", []), pdata.get("oldest_date")
        rate = "—"
        if od and items:
            try:
                days = max((now - datetime.strptime(od, "%Y%m%d").replace(tzinfo=timezone.utc)).days, 1)
                rate = f"{len(items)/days*7:.1f}"
            except Exception: pass
        out.append(f"| {(t['channel'] or '')[:26]} | {t['subs']:,} | {t['age_m']} мес | "
                   f"{len(items)} | {rate} |")

    # 7. темы-кандидаты
    out += ["", "## 10 тем-кандидатов", "",
            "| тема (EN) | почему | доказательство спроса |",
            "|-----------|--------|----------------------|"]
    for t in T[niche]:
        pv = idx.get(t.get("proof_video_id"))
        proof = (f"[{(pv['title'] or '')[:38]}]({yt(pv['id'])}) — {pv['views']:,} просм., "
                 f"канал {pv['ch_age_m']} мес" if pv else "—")
        out.append(f"| {t.get('title_en','')[:60]} | {t.get('why_ru','')[:90]} | {proof} |")
    out.append("")

dest = ROOT / "reports" / f"deepdive_{now.date().isoformat()}.md"
dest.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"{dest.relative_to(ROOT)} — {len(out)} строк")
