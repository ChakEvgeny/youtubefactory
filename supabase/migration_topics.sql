-- Очередь тем. Одна строка = кандидат в ролик.
create table if not exists topics (
    id           bigserial primary key,
    channel      text not null,
    niche        text not null,
    title        text not null,           -- рабочее название темы
    angle        text,                    -- под каким углом подавать
    event_date   date,                    -- дата события-повода
    summary      text,                    -- суть в одну строку
    why_story    text,                    -- почему это история: взлёт и падение
    sources      jsonb default '[]',      -- [{title, url}]
    analogues    jsonb default '[]',      -- [{url, title, views, channel, subs, channel_age_months, vs}]
    status       text not null default 'queued',   -- queued | in_progress | done | dropped
    priority     integer default 100,     -- меньше = раньше
    production_id text,                   -- связь с productions после выпуска
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists topics_queue_idx on topics (channel, status, priority);
