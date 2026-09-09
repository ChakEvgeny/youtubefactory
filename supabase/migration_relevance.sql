-- Миграция: релевантность нише + визуальный формат ролика.
-- Идемпотентна, можно выполнять повторно.
-- ВАЖНО: выполнять в том же проекте, что указан в SUPABASE_URL (.env).

-- 1 = ролик относится к нише, 0 = не относится, NULL = ещё не размечен.
alter table videos add column if not exists relevant smallint;
create index if not exists videos_relevant_idx on videos (lang, niche, relevant);

-- Обложка ролика (snippet.thumbnails.high.url) — вход для классификатора формата.
alter table videos add column if not exists thumbnail_url text;

-- Визуальный формат: stock_documentary | stickman_animation | whiteboard_2d |
-- ai_generated_visuals | talking_head | slideshow_text | gameplay_other
alter table videos add column if not exists format text;
create index if not exists videos_format_idx on videos (lang, niche, format);

-- Сколько из выживших роликов признаны релевантными нише.
alter table niche_scores add column if not exists n_relevant integer;

-- Проверка: должно вернуть 4 строки
-- select table_name, column_name from information_schema.columns
--  where (table_name='videos' and column_name in ('relevant','thumbnail_url','format'))
--     or (table_name='niche_scores' and column_name='n_relevant');
