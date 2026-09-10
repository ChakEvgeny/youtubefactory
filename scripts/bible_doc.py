#!/usr/bin/env python3
"""Собирает docs/format_bible_business.md из bible_data.json и thumbs.json."""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/mnt/d/youtube/cache/refs")
data = json.loads((R / "bible_data.json").read_text(encoding="utf-8"))
thumbs = json.loads((R / "thumbs.json").read_text(encoding="utf-8")) if (R / "thumbs.json").exists() else {}
sel = json.loads((R / "selection.json").read_text(encoding="utf-8"))
M = data["mondo startups"]["agg"]
C = {k: v["agg"] for k, v in data.items() if k != "mondo startups"}


def f(x, nd=1):
    if x is None:
        return "—"
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def pct_line(d: dict | None, top=6):
    if not d:
        return "—"
    items = [(k, v) for k, v in d.items() if v]
    return ", ".join(f"{k} {f(v,0)}%" for k, v in items[:top])


L = ["# Библия формата: business_breakdowns", "",
     f"Снято с референса, не придумано. Основа — **Mondo Startups**, {data['mondo startups']['n']} самых "
     "просмотренных роликов за 12 месяцев; контрольная группа — Logically Answered и JunkBondInvestor, "
     "по 2 самых просмотренных за 90 дней. Инструменты: ffmpeg scene-detect, Haiku vision по кадру "
     "каждые 2 с (сетки 3×3), автосубтитры YouTube, RMS-анализ звука. Замер 2026-09-10.", "",
     "## Выборка", "", "| канал | ролик | просмотры | дата | длина |", "|---|---|---:|---|---:|"]
for key, vids in sel.items():
    for v in vids:
        L.append(f"| {key} | {v['title'][:60]} | {v['views']:,} | {v['date']} | {v['dur']//60}:{v['dur']%60:02d} |")

L += ["", "## Ролик Mondo Startups состоит из…", "",
      f"**Длина.** Медиана {f(M['duration_min'])} мин. Темп публикаций — см. таблицу ниже.", "",
      f"**Монтаж.** {f(M['shots_per_min'])} кадров в минуту, медиана кадра **{f(M['shot_median'],2)} с** "
      f"(p10 {f(M['shot_p10'],2)}, p90 {f(M['shot_p90'],2)}). Ритм по секциям: хук {f(M['hook_median'],2)} с "
      f"({f(M['hook_per_min'])}/мин) → середина {f(M['middle_median'],2)} с ({f(M['middle_per_min'])}/мин) → "
      f"финал {f(M['tail_median'],2)} с ({f(M['tail_per_min'])}/мин).", "",
      f"**Переходы.** {pct_line(M.get('transitions'))}. Постоянное микродвижение внутри кадра — в "
      f"{f((M['micro_motion_share'] or 0)*100,0)}% кадров.", "",
      f"**Типы кадров** (доля времени): {pct_line(M.get('types'), 9)}.", "",
      f"**Текст на экране.** На {f(M['text_share'],0)}% кадров. Размер: {pct_line(M.get('text_size'))}. "
      f"Позиция: {pct_line(M.get('text_pos'))}. Фон: {pct_line(M.get('bg'))}. Лицо крупно — "
      f"{f(M['face_share'],0)}% кадров.", "",
      f"**Звук.** Речь {f(M['wpm'],0)} сл/мин по хронометражу, {f(M['wpm_speaking'],0)} в самой речи; "
      f"пауз >0.7 с — {f(M['pauses_per_min'])} в минуту. Музыка в паузах речи {f(M['music_in_pauses_db'])} dB "
      f"(постоянная подложка у {f((M['music_constant_share'] or 0)*100,0)}% роликов). SFX на стыках — "
      f"{f((M['sfx_at_cuts'] or 0)*100,0)}% проверенных смен кадра.", "",
      f"**Структура.** Цифр в речи — {f(M['numbers_per_min'])} в минуту. Первый поворот на "
      f"{f(M['first_turn_sec'],0)}-й секунде (медиана). Глав в описании — {f(M['chapters'],0)}.", ""]

# обложки
th = [thumbs[v["id"]] for v in sel["mondo startups"] if v["id"] in thumbs]
if th:
    words = [t.get("words") for t in th if isinstance(t.get("words"), int)]
    kinds = Counter(t.get("object_kind") for t in th)
    effs = Counter(e for t in th for e in (t.get("effects") or []) if e != "none")
    L += [f"**Обложка.** Слов: медиана {f(statistics.median(words),0) if words else '—'}. Главный объект: "
          f"{', '.join(f'{k} ×{v}' for k, v in kinds.most_common())}. Лицо — у {sum(1 for t in th if t.get('face'))} "
          f"из {len(th)}, логотип — у {sum(1 for t in th if t.get('logo'))} из {len(th)}. Фон тёмный — у "
          f"{sum(1 for t in th if t.get('bg')=='dark')} из {len(th)}. Эффекты: "
          f"{', '.join(f'{k} ×{v}' for k, v in effs.most_common())}.", ""]
    L += ["| ролик | текст обложки | объект | эффекты |", "|---|---|---|---|"]
    for v in sel["mondo startups"]:
        t = thumbs.get(v["id"], {})
        L.append(f"| {v['title'][:40]} | «{t.get('text','')}» | {t.get('object_kind')} ({t.get('object_pos')}) | {', '.join(t.get('effects') or [])} |")
    L.append("")

L += ["## Контрольная группа", "", "| метрика | Mondo | " + " | ".join(C.keys()) + " |",
      "|---|---:|" + "---:|" * len(C)]
for kk, label in (("shots_per_min", "кадров/мин"), ("shot_median", "медиана кадра, с"), ("hook_median", "хук, с"),
                  ("text_share", "текст на экране, %"), ("face_share", "лицо, %"), ("wpm", "сл/мин"),
                  ("numbers_per_min", "цифр/мин"), ("duration_min", "длина, мин"), ("micro_motion_share", "микродвижение")):
    L.append(f"| {label} | {f(M.get(kk))} | " + " | ".join(f(c.get(kk)) for c in C.values()) + " |")
L += ["", "Типы кадров у контрольной группы:", ""]
for k, c in C.items():
    L.append(f"- {k}: {pct_line(c.get('types'), 8)}")

# длина, mid-roll, числа — из autopsy_length.py
LEN = json.loads((R / "length.json").read_text(encoding="utf-8")) if (R / "length.json").exists() else {}
if LEN:
    L += ["", "## Длина, mid-roll и числа против просмотров", "",
          "| | Mondo (26, 12 мес) | Logically Answered (120, 12 мес) |", "|---|---|---|"]
    m, la = LEN["mondo_startups"], LEN["logically_answered"]
    def bins(v): return "; ".join(f"{b}: {d['n']} рол., медиана {d['median_views']:,}" for b, d in v["views_by_length_bin"].items())
    def nt(v): return f"с числом {v['with'][0]} → {v['with'][1] or '—'}; без {v['without'][0]} → {v['without'][1] or '—'}"
    L += [f"| длина, медиана (IQR) | {m['duration_median_min']} мин ({m['duration_iqr_min'][0]}–{m['duration_iqr_min'][1]}) | {la['duration_median_min']} мин ({la['duration_iqr_min'][0]}–{la['duration_iqr_min'][1]}) |",
          f"| mid-roll помещается* | {m['midrolls_median']} ({m['midrolls_at_iqr'][0]}–{m['midrolls_at_iqr'][1]}) | {la['midrolls_median']} ({la['midrolls_at_iqr'][0]}–{la['midrolls_at_iqr'][1]}) |",
          f"| просмотры по длине | {bins(m)} | {bins(la)} |",
          f"| число в заголовке (n → медиана просм.) | {nt(m['title_number'])} | {nt(la['title_number'])} |",
          f"| число на обложке, топ-20 | {nt(m['thumb_number_top20'])} | {nt(la['thumb_number_top20'])} |", "",
          "\\* допущение: mid-roll от 8 мин, один слот на ~2.5 мин после первой минуты.", "",
          "**Вывод по длине.** У Mondo 22 из 26 роликов — 8–12 мин с медианой 14.5k просмотров, а три ролика 12–15 мин "
          "дали медиану 290k (в них же — топ канала). У Logically Answered 15–20 мин (62 ролика) — 228k против 129k у 8–12 мин. "
          "Длиннее выигрывает в обеих выборках; **предложение: целевая длина `business` 12–15 мин вместо 10–13** "
          "(+1–2 mid-roll). Число в заголовке у Mondo не встречается вовсе; у LA заголовки с числом — 306k против 200k, "
          "обложки с числом в топ-20 — 1.1M против 646k. У Mondo обложки с числом (7 из 20) проигрывают (13k против 83k) — "
          "но там число это год/версия, не сумма. Правило: число — только сумма денег или доля рынка, из брифа.", ""]

# темп публикаций
L += ["", "## Темп публикаций", ""]
for key in sel:
    lst = json.loads((R / f"list_{key.replace(' ', '_')}.json").read_text(encoding="utf-8"))
    d90 = [r for r in lst if r.get("age_days") is not None and r["age_days"] <= 90]
    d365 = [r for r in lst if r.get("age_days") is not None and r["age_days"] <= 365]
    L.append(f"- {key}: {len(d90)} роликов за 90 дней ({len(d90)/90*7:.1f}/нед), {len(d365)} за год")

T = M.get("types", {})
def tp(k):
    return f"{f(T.get(k, 0), 0)}%"
L += ["", "## Что из этого умеет наш конвейер", "",
      "Доли — замер Mondo (время в кадре). real-footage у нас нет и не будет (чужая съёмка): его долю "
      "закрывают карточки прессы (fair use ≤4 с) и коллажи — см. `format.footage_rule` в конфиге.", "",
      "| элемент формата | референс | у нас | статус |", "|---|---|---|---|",
      f"| кадров/мин, медиана кадра | {f(M['shots_per_min'])}, {f(M['shot_median'],2)} с | shotlist режет по `format.pacing` | ✅ из библии |",
      f"| article-screenshot | {tp('article-screenshot')} | стадия screens (Playwright + PressCard), источник — факты брифа | ✅ fair use ≤4 с, источник в описании |",
      f"| real-footage (новости, интервью) | {tp('real-footage')} | нет яруса → screens 60% / collage 40% | ⚠️ заменяем |",
      f"| stock-video | {tp('stock-video')} | Pexels/Pixabay, только кадры без субъекта | ✅ по правилу — не на субъекте |",
      f"| logo/brand card | {tp('logo-brand-card')} | BrandCard: вордмарк из названия, без чужих файлов | ✅ по правилу честности |",
      f"| text-kinetic | {tp('text-kinetic')} | Callout | ✅ визуально беднее референса |",
      f"| cutout-collage | {tp('cutout-collage')} | стадия collage (Commons + rembg + Remotion) | ✅ |",
      f"| chart/graph | {tp('chart-graph')} | Chart / Counter (Remotion) | ✅ |",
      f"| ai-image | {tp('ai-image')} | Kling не подключён | ❌ нет |",
      f"| текст на экране | {f(M['text_share'],0)}% кадров, center {f((M.get('text_pos') or {}).get('center',0),0)}% | подпись на коллаже, заголовок на карточке прессы, callout | ✅ |",
      f"| микродвижение в кадре | {f((M['micro_motion_share'] or 0)*100,0)}% | push-in / zoom-out / Ken Burns | ✅ |",
      f"| переходы | {pct_line(M.get('transitions'))} | hard cut + dip; xfade нет | ⚠️ soft заменяем dip |",
      f"| музыка постоянно + ducking | {f(M['music_in_pauses_db'])} dB в паузах | огибающая по таймкодам, −12 dB | ✅ |",
      f"| SFX на стыках | {f((M['sfx_at_cuts'] or 0)*100,0)}% стыков | нет | ❌ нет |",
      f"| темп речи | {f(M['wpm'],0)} сл/мин | atempo {f(min(max((M['wpm'] or 154)/154,0.95),1.15),3)} | ✅ |",
      "| обложка: логотип + 1–4 слова + огонь/трещина, тёмный фон | да | thumbs: кадр + плашка | ⚠️ нужен режим «вордмарк + эффект» |",
      "", "## Заголовки", "",
      "Скелеты — в `config/title_skeletons_business.yaml` (топ-20 Mondo + топ-20 LA → 10 семейств масок, частота, средние просмотры). "
      "Стадия meta генерирует заголовки только по этим маскам. Медиана длины 39 символов, многоточие — в 18 из 40, скобки — в 2.", "",
      "", "## Что мы добавляем от себя (и не отменяем)", "",
      "- **Факты только с источником**: brief.md, каждый тезис — ссылка и дата; критик режет всё без опоры.",
      "- **Quote-карточки реальных людей** вместо чужих лиц из стока: имя, должность, дословная цитата.",
      "- **Честные обложки**: без чужих лиц, без плашек СМИ, без «BREAKING»; логотип — вордмарк из названия, не файл бренда.",
      "- **Атрибуция CC-изображений** в кадре и в описании; лог лицензий в паспорте ролика.",
      "- **Пресс-медиа производителей не используем** (User Licence JLR — NC), fair-use фрагменты прессы ≤4 с.", ""]
out = ROOT / "docs" / "format_bible_business.md"
out.write_text("\n".join(L) + "\n", encoding="utf-8")
print(f"{out.relative_to(ROOT)}: {len(L)} строк")
