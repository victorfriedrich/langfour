-- The dictionary and the user's word statuses, for classifying text in the
-- extension instead of in the database.
--
-- classify_words (classify_words.sql) answers per article, and each article
-- touches pages scattered over words, wordforms and their indexes (264 MB,
-- most of it invalid rows), which a small instance does not keep in memory:
-- a long Wikipedia article took ~9 s cold and could run into the
-- authenticated role's 8 s statement timeout. The valid dictionary of a
-- language is only ~3 MB, so the extension downloads it once
-- (apps/extension/src/lexicon.ts) and matches tokens itself, with the same
-- rules as classify_words.
--
-- HOW THIS GETS APPLIED: through the Supabase connector, like the other
-- files here. Idempotent. Then fill the pages once per language:
--   select public.rebuild_lexicon_pages('es');

-- The dictionary pages, built ahead of time. Building a page reads 10k
-- words and their forms from pages spread over words and wordforms; on a
-- database that has been idle, that took longer than the authenticated
-- role's 8 s statement timeout, so the extension's first download failed.
-- A stored page is one row of text, which reads quickly even cold.
--
-- entries: one line per word, "id<TAB>root<TAB>form<TAB>form...", forms
-- being the valid word forms other than the root (audit status, like
-- classify_words). Text, not rows, because PostgREST caps a response at
-- 1000 rows and 300k rows of JSON would be three times the size.
create table if not exists public.lexicon_pages (
    language     text        not null,
    last_word_id integer     not null,
    entries      text        not null,
    built_at     timestamptz not null default now(),
    primary key (language, last_word_id)
);

alter table public.lexicon_pages enable row level security;
drop policy if exists lexicon_pages_select_authenticated on public.lexicon_pages;
create policy lexicon_pages_select_authenticated on public.lexicon_pages
    for select to authenticated using (true);

-- Rebuilds a language's pages from words and wordforms, in one
-- transaction, so readers see the old pages or the new ones. Run after
-- the dictionary changes (audits, merges); takes a few seconds.
create or replace function public.rebuild_lexicon_pages(language_filter text, page_words integer default 10000)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
    after_id integer := 0;
    built integer := 0;
    page_last integer;
    page_entries text;
begin
    delete from public.lexicon_pages where language = language_filter;
    loop
        with page as (
            select w.id, w.root
            from public.words w
            where w.language = language_filter
              and w.status = 'valid'
              and w.id > after_id
            order by w.id
            limit page_words
        )
        select max(p.id),
               string_agg(p.id || E'\t' || p.root || coalesce(E'\t' || f.forms, ''), E'\n' order by p.id)
        into page_last, page_entries
        from page p
        left join lateral (
            select string_agg(wf.form, E'\t') as forms
            from public.wordforms wf
            where wf.word_id = p.id
              and wf.status = 'valid'
              and wf.form <> p.root
        ) f on true;
        exit when page_last is null;
        insert into public.lexicon_pages (language, last_word_id, entries)
        values (language_filter, page_last, page_entries);
        after_id := page_last;
        built := built + 1;
    end loop;
    return built;
end;
$$;

revoke execute on function public.rebuild_lexicon_pages(text, integer) from public, anon, authenticated;

-- The stored page after after_word_id (start with 0): pass the returned
-- last_word_id as after_word_id for the next page; no row means there are
-- no more. page_words is kept for older clients and ignored: pages are
-- the size they were built with.
create or replace function public.lexicon_page(language_filter text, after_word_id integer, page_words integer)
returns table (last_word_id integer, entries text)
language sql
stable
security invoker
set search_path = ''
as $$
    select lp.last_word_id, lp.entries
    from public.lexicon_pages lp
    where lp.language = language_filter
      and lp.last_word_id > after_word_id
    order by lp.last_word_id
    limit 1;
$$;

grant execute on function public.lexicon_page(text, integer, integer) to authenticated;

-- The signed-in user's status for every word they have a relation to, as
-- [[word_id, status], ...]; words not listed are 'new'. Statuses as in
-- classify_words: 'known' (user_known_words), 'ignored' (userwords
-- 'disabled'), 'learning' (any other userwords row). All languages: the
-- caller only looks up ids from its own language's dictionary. jsonb, not
-- rows, for the same 1000-row cap.
create or replace function public.my_word_statuses()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    with mine as (
        select uw.word_id, uw.status
        from public.userwords uw
        where uw.user_id = (select auth.uid())
    ),
    known as (
        select k.word_id
        from public.user_known_words k
        where k.user_id = (select auth.uid())
    )
    select coalesce(jsonb_agg(jsonb_build_array(s.word_id, s.status)), '[]'::jsonb)
    from (
        select coalesce(m.word_id, k.word_id) as word_id,
               case
                   when k.word_id is not null then 'known'
                   when m.status = 'disabled' then 'ignored'
                   else 'learning'
               end as status
        from mine m
        full join known k on k.word_id = m.word_id
        -- classify_words treats a userwords row without a status as new.
        where k.word_id is not null or m.status is not null
    ) s;
$$;

grant execute on function public.my_word_statuses() to authenticated;
