-- Паспорта выпущенных роликов. Одна строка = один ролик.
create table if not exists productions (
    id            text primary key,          -- <channel>/<YYYY-MM-DD>_<slug>
    channel       text not null,
    niche         text not null,
    slug          text not null,
    topic         text,
    title         text,
    titles_alt    jsonb,                     -- варианты заголовков
    lang          text default 'en',
    duration_sec  integer,
    n_scenes      integer,
    scene_sources jsonb,                     -- {pexels_video: 12, pixabay: 3, kling: 4, photo: 6}
    sources       jsonb,                     -- факты и ссылки из brief
    models        jsonb,                     -- {script: ..., critic: ..., research: ...}
    voice_id      text,
    voice_model   text,
    critic_notes  jsonb,                     -- сводка правок критика
    cost          jsonb,                     -- стоимость по стадиям, USD
    cost_total    numeric(10,4),
    out_dir       text,
    nas_synced    boolean default false,
    created_at    timestamptz not null default now()
);
create index if not exists productions_channel_idx on productions (channel, created_at desc);
create index if not exists productions_created_idx on productions (created_at desc);
