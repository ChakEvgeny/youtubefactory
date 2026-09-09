-- Причина, по которой ролику проставлен relevant=0.
-- Значения: 'lang_leak' — заголовок не на языке ниши (утечка языкового фильтра);
--           NULL — снято классификатором релевантности по смыслу.
alter table videos add column if not exists relevance_reason text;
create index if not exists videos_reason_idx on videos (lang, relevance_reason);
