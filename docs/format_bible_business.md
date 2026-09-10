# Библия формата: business_breakdowns

Снято с референса, не придумано. Основа — **Mondo Startups**, 5 самых просмотренных роликов за 12 месяцев; контрольная группа — Logically Answered и JunkBondInvestor, по 2 самых просмотренных за 90 дней. Инструменты: ffmpeg scene-detect, Haiku vision по кадру каждые 2 с (сетки 3×3), автосубтитры YouTube, RMS-анализ звука. Замер 2026-09-10.

## Выборка

| канал | ролик | просмотры | дата | длина |
|---|---|---:|---|---:|
| logically answered | $1 Billion To Forgotten: How Dollar Shave Club Lost Everythi | 1,100,000 | 20260810 | 15:32 |
| logically answered | The Carvana Situation Gets Worse... | 518,000 | 20260810 | 13:54 |
| mondo startups | The Deserved Death of McAfee Antivirus | 797,000 | 20260810 | 12:53 |
| mondo startups | The Deserved Death of HP Printers | 290,000 | 20260827 | 13:15 |
| mondo startups | The Satisfying Death of Stack Overflow | 264,000 | 20260710 | 11:07 |
| mondo startups | How Perplexity Lost the AI War | 239,000 | 20260310 | 9:16 |
| mondo startups | The AI Coding Boom Is Backfiring | 236,000 | 20260810 | 10:12 |
| junkbondinvestor | Sriracha: How a Greedy Owner Ruined a $1B Sauce Empire | 820,000 | 20260820 | 13:43 |
| junkbondinvestor | Jaguar: How A Delusional Rebrand Killed An $12.3B Icon | 509,000 | 20260827 | 13:20 |

## Ролик Mondo Startups состоит из…

**Длина.** Медиана 11.1 мин. Темп публикаций — см. таблицу ниже.

**Монтаж.** 12.2 кадров в минуту, медиана кадра **3.87 с** (p10 1.50, p90 8.96). Ритм по секциям: хук 3.71 с (12.0/мин) → середина 3.92 с (12.1/мин) → финал 3.55 с (12.0/мин).

**Переходы.** soft 20%, hard 80%. Постоянное микродвижение внутри кадра — в 83% кадров.

**Типы кадров** (доля времени): article-screenshot 31%, real-footage 26%, stock-video 12%, logo-brand-card 7%, text-kinetic 5%, cutout-collage 4%, chart-graph 4%, ai-image 4%, black-or-empty 1%.

**Текст на экране.** На 75% кадров. Размер: medium 26%, small 27%, none 25%, large 19%. Позиция: center 51%, top 25%, bottom 13%, none 6%, left 1%, right 1%. Фон: light 53%, dark 33%, color 14%. Лицо крупно — 26% кадров.

**Звук.** Речь 162 сл/мин по хронометражу, 168 в самой речи; пауз >0.7 с — 14.8 в минуту. Музыка в паузах речи -25.6 dB (постоянная подложка у 100% роликов). SFX на стыках — 12% проверенных смен кадра.

**Структура.** Цифр в речи — 1.4 в минуту. Первый поворот на 28-й секунде (медиана). Глав в описании — 4.

**Обложка.** Слов: медиана 4. Главный объект: building ×2, logo ×2, person ×1. Лицо — у 1 из 5, логотип — у 4 из 5. Фон тёмный — у 5 из 5. Эффекты: fire ×4, glow ×4, arrow ×1, crack ×1.

| ролик | текст обложки | объект | эффекты |
|---|---|---|---|
| The Deserved Death of McAfee Antivirus | «PLEASE DON'T UNINSTALL» | building (center) | fire, arrow, glow |
| The Deserved Death of HP Printers | «HP IS FALLING» | logo (center) | fire, crack, glow |
| The Satisfying Death of Stack Overflow | «BANKRUPT» | person (center) | none |
| How Perplexity Lost the AI War | «We lost... Us > Google» | logo (left) | fire, glow |
| The AI Coding Boom Is Backfiring | «"WE NEED DEVS BACK"» | building (center) | fire, glow |

## Контрольная группа

| метрика | Mondo | logically answered | junkbondinvestor |
|---|---:|---:|---:|
| кадров/мин | 12.2 | 11.2 | 14.8 |
| медиана кадра, с | 3.9 | 3.0 | 2.9 |
| хук, с | 3.7 | 10.0 | 5.8 |
| текст на экране, % | 75.4 | 83.3 | 76.2 |
| лицо, % | 26.1 | 27.6 | 28.1 |
| сл/мин | 162 | 156.0 | 142.5 |
| цифр/мин | 1.4 | 4.4 | 6.2 |
| длина, мин | 11.1 | 14.7 | 13.5 |
| микродвижение | 0.8 | 0.7 | 0.7 |

Типы кадров у контрольной группы:

- logically answered: article-screenshot 40%, real-footage 30%, stock-video 8%, cutout-collage 6%, chart-graph 6%, logo-brand-card 5%, text-kinetic 4%, ai-image 2%
- junkbondinvestor: real-footage 43%, article-screenshot 30%, stock-video 6%, cutout-collage 6%, chart-graph 4%, text-kinetic 4%, ai-image 4%, logo-brand-card 3%

## Длина, mid-roll и числа против просмотров

| | Mondo (26, 12 мес) | Logically Answered (120, 12 мес) |
|---|---|---|
| длина, медиана (IQR) | 10.2 мин (9.5–11.2) | 15.1 мин (13.8–16.4) |
| mid-roll помещается* | 3 (3–4) | 5 (5–6) |
| просмотры по длине | 8–12: 22 рол., медиана 14,500; 12–15: 3 рол., медиана 290,000; 15–20: 1 рол., медиана 83,000 | 8–12: 6 рол., медиана 129,000; 12–15: 52 рол., медиана 212,500; 15–20: 62 рол., медиана 228,000 |
| число в заголовке (n → медиана просм.) | с числом 0 → —; без 26 → 17500 | с числом 33 → 306000; без 87 → 200000 |
| число на обложке, топ-20 | с числом 7 → 13000; без 13 → 83000 | с числом 11 → 1100000; без 9 → 646000 |

\* допущение: mid-roll от 8 мин, один слот на ~2.5 мин после первой минуты.

**Вывод по длине.** У Mondo 22 из 26 роликов — 8–12 мин с медианой 14.5k просмотров, а три ролика 12–15 мин дали медиану 290k (в них же — топ канала). У Logically Answered 15–20 мин (62 ролика) — 228k против 129k у 8–12 мин. Длиннее выигрывает в обеих выборках; **предложение: целевая длина `business` 12–15 мин вместо 10–13** (+1–2 mid-roll). Число в заголовке у Mondo не встречается вовсе; у LA заголовки с числом — 306k против 200k, обложки с числом в топ-20 — 1.1M против 646k. У Mondo обложки с числом (7 из 20) проигрывают (13k против 83k) — но там число это год/версия, не сумма. Правило: число — только сумма денег или доля рынка, из брифа.


## Темп публикаций

- logically answered: 23 роликов за 90 дней (1.8/нед), 120 за год
- mondo startups: 13 роликов за 90 дней (1.0/нед), 26 за год
- junkbondinvestor: 26 роликов за 90 дней (2.0/нед), 97 за год

## Что из этого умеет наш конвейер

Доли — замер Mondo (время в кадре). real-footage у нас нет и не будет (чужая съёмка): его долю закрывают карточки прессы (fair use ≤4 с) и коллажи — см. `format.footage_rule` в конфиге.

| элемент формата | референс | у нас | статус |
|---|---|---|---|
| кадров/мин, медиана кадра | 12.2, 3.87 с | shotlist режет по `format.pacing` | ✅ из библии |
| article-screenshot | 31% | стадия screens (Playwright + PressCard), источник — факты брифа | ✅ fair use ≤4 с, источник в описании |
| real-footage (новости, интервью) | 26% | нет яруса → screens 60% / collage 40% | ⚠️ заменяем |
| stock-video | 12% | Pexels/Pixabay, только кадры без субъекта | ✅ по правилу — не на субъекте |
| logo/brand card | 7% | BrandCard: вордмарк из названия, без чужих файлов | ✅ по правилу честности |
| text-kinetic | 5% | Callout | ✅ визуально беднее референса |
| cutout-collage | 4% | стадия collage (Commons + rembg + Remotion) | ✅ |
| chart/graph | 4% | Chart / Counter (Remotion) | ✅ |
| ai-image | 4% | Kling не подключён | ❌ нет |
| текст на экране | 75% кадров, center 51% | подпись на коллаже, заголовок на карточке прессы, callout | ✅ |
| микродвижение в кадре | 83% | push-in / zoom-out / Ken Burns | ✅ |
| переходы | soft 20%, hard 80% | hard cut + dip; xfade нет | ⚠️ soft заменяем dip |
| музыка постоянно + ducking | -25.6 dB в паузах | огибающая по таймкодам, −12 dB | ✅ |
| SFX на стыках | 12% стыков | нет | ❌ нет |
| темп речи | 162 сл/мин | atempo 1.052 | ✅ |
| обложка: логотип + 1–4 слова + огонь/трещина, тёмный фон | да | thumbs: кадр + плашка | ⚠️ нужен режим «вордмарк + эффект» |

## Заголовки

Скелеты — в `config/title_skeletons_business.yaml` (топ-20 Mondo + топ-20 LA → 10 семейств масок, частота, средние просмотры). Стадия meta генерирует заголовки только по этим маскам. Медиана длины 39 символов, многоточие — в 18 из 40, скобки — в 2.


## Что мы добавляем от себя (и не отменяем)

- **Факты только с источником**: brief.md, каждый тезис — ссылка и дата; критик режет всё без опоры.
- **Quote-карточки реальных людей** вместо чужих лиц из стока: имя, должность, дословная цитата.
- **Честные обложки**: без чужих лиц, без плашек СМИ, без «BREAKING»; логотип — вордмарк из названия, не файл бренда.
- **Атрибуция CC-изображений** в кадре и в описании; лог лицензий в паспорте ролика.
- **Пресс-медиа производителей не используем** (User Licence JLR — NC), fair-use фрагменты прессы ≤4 с.

