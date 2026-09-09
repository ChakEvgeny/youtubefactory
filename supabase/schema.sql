-- YouTube niche scanner — схема кэша и результатов.
-- Идемпотентно: можно выполнять повторно.

-- Кэш вызовов search.list. Одна строка = один оплаченный запрос (100 units).
create table if not exists searches (
    id              bigserial primary key,
    cache_key       text not null unique,
    lang            text not null,
    region          text not null,
    niche           text not null,
    query           text not null,
    published_after timestamptz not null,
    order_by        text not null,
    video_ids       jsonb not null default '[]'::jsonb,
    units_spent     integer not null default 0,
    created_at      timestamptz not null default now()
);
create index if not exists searches_lang_niche_idx on searches (lang, niche);
create index if not exists searches_created_at_idx on searches (created_at desc);

-- Кэш videos.list.
create table if not exists videos (
    id                     text primary key,
    channel_id             text,
    title                  text,
    description            text,
    published_at           timestamptz,
    duration_sec           integer,
    view_count             bigint,
    like_count             bigint,
    comment_count          bigint,
    default_language       text,
    default_audio_language text,
    detected_lang          text,
    lang                   text,
    niche                  text,
    fetched_at             timestamptz not null default now()
);
create index if not exists videos_lang_niche_idx on videos (lang, niche);
create index if not exists videos_channel_idx on videos (channel_id);
create index if not exists videos_fetched_at_idx on videos (fetched_at desc);

-- Кэш channels.list. created_at = дата создания канала на YouTube (snippet.publishedAt),
-- fetched_at = когда мы последний раз тянули его из API.
create table if not exists channels (
    id               text primary key,
    title            text,
    subscriber_count bigint,
    video_count      bigint,
    view_count       bigint,
    created_at       timestamptz,
    country          text,
    fetched_at       timestamptz not null default now()
);
create index if not exists channels_fetched_at_idx on channels (fetched_at desc);

-- Итоговые метрики по паре язык x ниша за прогон.
create table if not exists niche_scores (
    lang           text not null,
    niche          text not null,
    run_date       date not null,
    demand_views   bigint,
    n_videos       integer,
    competition    integer,
    newcomer_share double precision,
    anomalies      integer,
    rpm_estimate   double precision,
    score          double precision,
    details        jsonb,
    primary key (lang, niche, run_date)
);
create index if not exists niche_scores_score_idx on niche_scores (run_date desc, score desc);
