# Ярусы источников кадров и что по ним выяснено

Проверено 2026-09-10 на живых сайтах и API. Порядок приоритета — сверху вниз.
Правило из CLAUDE.md: кадры про конкретную компанию, площадку, модель или
человека идут только из ярусов (а)–(в); сток — никогда.

## (а) Wikimedia Commons — основной ярус

- API без ключа, `pipeline/sources/commons.py`. Берём только свободные
  лицензии: CC0 / PD / OGL / GODL / CC BY / CC BY-SA. NC, ND, fair-use — отсев.
- Что нашлось по JLR-ролику: Sharon Graham (CC0, CC BY 4.0), портреты
  Jonathan Reynolds (CC0, CC BY 3.0), визит премьера на Solihull (Number 10,
  CC BY 2.0), завод Halewood (CC BY-SA 4.0), Defender 2020 (CC BY 4.0).
- Атрибуция: для CC BY / CC BY-SA — строка в углу кадра
  (`© автор · лицензия · Wikimedia Commons`) и список в описании ролика.
  Для CC BY-SA формально нужна та же лицензия на производное — на практике
  для видео с кадром внутри принято считать коллекцией, но это серая зона;
  при выборе между CC BY и CC BY-SA берём CC BY.
- Ловушка: первый кандидат по имени часто групповой снимок (Sharon Graham
  в толпе). Vision-отбор обязан проверять «названный субъект — единственный
  и главный в кадре», запросы по людям тянем к «portrait».

## (б) Пресс-медиа производителей — НЕ ИСПОЛЬЗУЕМ

**JLR** (media.jaguarlandrover.com): сайт открыт без логина, пресс-киты
скачиваются, но User Licence (`/user-licence`) — по образцу CC BY-NC:

> 4(b) You may not exercise any of the rights granted … in any manner that is
> primarily intended for or directed toward commercial advantage or private
> monetary compensation.

Монетизируемый канал — коммерческое использование. §4(d)(ii) отделяет
«commercial (non-editorial)» от editorial, но editorial там — пресса, не мы.
Общие Terms of Use говорят то же: «must not use … for commercial purposes
without obtaining a written licence». **Вывод: только по письменной лицензии.**

Stellantis media — HTTP 403 для ботов; Tata newsroom — упоминает логин;
VW newsroom — открыт, условия не проверялись, потому что и не нужны:
для этого ролика VW не субъект.

## (в) Fair use — карточки прессы

Скриншот шапки статьи (издание, дата, заголовок) через Playwright, ≤4 с в кадре,
только под комментарий, источник в описании и в паспорте. `pipeline/stages/screens.py`.
Сайты с защитой от headless (ITV: ERR_HTTP2_PROTOCOL_ERROR даже без HTTP/2)
пропускаем — берём другой источник из brief.

## (г) Flickr CC — ждёт ключ

API требует `FLICKR_API_KEY` (бесплатная регистрация). В `.env` его нет.
Модуль не написан, пока ключа нет.

## (д) Google Earth Studio — API не существует

Earth Studio — веб-приложение под аккаунт Google, рендер только через
браузер вручную; программного доступа нет. Ближайшие честные замены:
аэрофото площадок с Commons + Ken Burns (для Solihull и Halewood они есть);
Google Maps Static API требует ключ и запрещает использование в видео по ToS;
Sentinel-2 (открытые данные) — 10 м/пиксель, для заводов непригодно.
**Пролёты над площадками пока делаем как Ken Burns по фото Commons.**

## (е) Сток (Pexels / Pixabay) — только текстура

≤10 % кадров, только `[BEAT: story]` без субъекта. На кадре с названным
субъектом сток запрещён: лучше brand/quote-карточка, чем чужое лицо или
чужой завод под нашим текстом.
