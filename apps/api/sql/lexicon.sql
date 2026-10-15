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
-- files here. Idempotent.

-- One page of a language's valid words, by word id, as text: one line per
-- word, "id<TAB>root<TAB>form<TAB>form...", forms being the valid word
-- forms other than the root (audit status, like classify_words). Text,
-- not rows, because PostgREST caps a response at 1000 rows and 300k rows
-- of JSON would be three times the size. Pass the returned last_word_id
-- as after_word_id for the next page; a null last_word_id means there are
-- no more.
create or replace function public.lexicon_page(language_filter text, after_word_id integer, page_words integer)
returns table (last_word_id integer, entries text)
language sql
stable
security invoker
set search_path = ''
as $$
    with page as (
        select w.id, w.root
        from public.words w
        where w.language = language_filter
          and w.status = 'valid'
          and w.id > after_word_id
        order by w.id
        limit least(page_words, 20000)
    )
    select max(p.id),
           string_agg(p.id || E'\t' || p.root || coalesce(E'\t' || f.forms, ''), E'\n' order by p.id)
    from page p
    left join lateral (
        select string_agg(wf.form, E'\t') as forms
        from public.wordforms wf
        where wf.word_id = p.id
          and wf.status = 'valid'
          and wf.form <> p.root
    ) f on true;
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
