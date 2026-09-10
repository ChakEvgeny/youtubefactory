-- Откуда пришла тема: manual | scan | comments (audience-стадия)
alter table topics add column if not exists source text not null default 'manual';
create index if not exists topics_source_idx on topics (source);
