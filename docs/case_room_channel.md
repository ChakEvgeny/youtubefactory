# The Case Room — как делать ролики канала

Канал `@CaseRoomFiles` (бывший Technically Legal, переименован 2026-09-18; папка
проектов — `/mnt/d/youtube/output/heists/`). Настоящие дела: мошенничество,
аферы, ограбления, скандалы и как они раскрылись. Нуар-комикс × ризограф.
8–12 минут, английский. Голос James `jtE6dbPUTt2kchN89Uej`, ×1.08 — не менять.

Вышло: Salad Oil Swindle (1963), Knoedler (подделки на $80M), Clifford Irving и
фальшивый Хьюз (1972). Раньше, в старом формате: Ларсон, Cash WinFall, Google/Facebook.

## Темы

«Человек обыграл систему» выработана миллионниками. Свободная подниша —
**мошенничество через документы** (расписки, счета, провенанс, поддельные письма).
Отложено: First Brands (обвиняемые не осуждены — ждать процесса, февраль 2027),
Wirecard (ждать приговора).

## Конвейер (тот же, что у Survivor's Notebook, другой профиль)

Папка проекта содержит, кроме общих файлов (`brief.json`, `facts_extra.md`,
`script.md`, `cast.json`, `scrap_plan.json`):
- `style.txt` и `styletest/ref.jpg` — копировать из прошлого ролика канала;
- `format.json` — формат раскадровки (нуар-панели, карточка-улика, акцент жёлтый);
- `build.json` — профиль сборки: интро `brand_noir/intro/INTRO_case_room.mp4`,
  музыка `noir_main.mp3` / `noir_end.mp3`, `resolve_at` — фраза, с которой
  включается финальный трек, `cut: NoirCut`, `card: Evidence`, `outro: NoirOutro`,
  `card_direct: true`.

Шаги: `notebook_board.py` → `notebook_scenes.py` → `voice_blocks.py --speed 1.08`
→ `notebook_build.py` → loudnorm −14 → `thumbs.py --theme bare --colour yellow
--font ~/.fonts/Anton.ttf` (8 вариантов) → `make_srt.py` → `translate_subs.py`
→ `release_pack.py`.

## Стиль

Густая тушь, светотень, растр ризографа на кремовой бумаге; чёрный + стальной
синий + ОДИН горчично-жёлтый акцент. Шрифты: Anton (плашки, числа), Special Elite
(машинопись). Интро — три панели и жёлтая плашка «THE CASE ROOM»; граница блока —
панель въезжает через чёрный зазор; инфографика — карточка из дела со скрепкой
(`Evidence`: letter / counter / date / flow / bars / tally / tank); аутро —
плашка THE END. Баннер и иконка: `brand_noir/channel/`.

## Юридическая осторожность

- Живые и не осуждённые люди — только факты суда, их собственные слова,
  формулировки «prosecutors allege», «testified». Ни «fraudster», ни «scammer»
  про таких людей в заголовке и на обложке.
- Цитаты — только проверенные дословно (цитата Хьюза «any script as good as
  this one» в популярной версии не подтвердилась).
- Лица реальных людей — типажи в тени, без портретного сходства; логотипов
  компаний не рисуем.
