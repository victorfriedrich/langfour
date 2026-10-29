-- A user's vocabulary for an AI app connected over MCP (get_vocabulary in
-- apps/api/mcp_server.py).
--
-- The API calls this with the service role on behalf of an OAuth user, whose
-- token can't reach the Data API (docs/mcp-oauth.md), so the user is a
-- parameter and only service_role may execute it.
--
-- Every word the user has decided on is in userwords; 'disabled' ones are left
-- out. Known means user_known_words (declared, or proven in reviews), so the
-- same words count as known here as on the Vocabulary page. A learning word
-- is due when a live card of it, with the user's current scheduler
-- (userdata.review_provider), is due now.
--
--   p_language  ISO code; null means the user's default_language
--   p_status    which words to list: 'due' (most overdue first), 'learning'
--               or 'known' (both newest first). The counts always cover all.
--
-- Returns {language, counts: {known, learning, due}, words: [{word,
-- translation, status, due}]}.
--
-- HOW THIS GETS APPLIED: through the Supabase connector, like the other
-- files here. Idempotent.

create or replace function public.mcp_vocabulary(p_user_id uuid, p_language text,
                                                 p_status text, p_limit integer)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    with settings as (
        select coalesce(p_language, d.default_language) as language,
               coalesce(d.review_provider, 'langfour') as provider
        from (select 1) one
        left join public.userdata d on d.user_id = p_user_id
        limit 1
    ),
    mine as (
        select uw.word_id, w.root, uw.created_at,
               coalesce(ut.custom_translation, w.translation) as translation,
               exists (select 1 from public.user_known_words k
                       where k.user_id = p_user_id and k.word_id = uw.word_id) as known
        from public.userwords uw
        join public.words w on w.id = uw.word_id
        left join public.usertranslations ut on ut.user_id = p_user_id and ut.word_id = uw.word_id
        where uw.user_id = p_user_id
          and uw.status <> 'disabled'
          and w.language = (select language from settings)
    ),
    due as (
        select n.word_id, min(c.next_due_at) as due_at
        from public.srs_notes n
        join public.srs_cards c on c.note_id = n.id
        where n.user_id = p_user_id
          and n.provider = (select provider from settings)
          and n.removed_at is null
          and n.word_id in (select word_id from mine where not known)
        group by n.word_id
    ),
    rated as (
        select m.root, m.translation, m.created_at, d.due_at,
               case when m.known then 'known' else 'learning' end as status,
               coalesce(d.due_at <= now(), false) as is_due
        from mine m
        left join due d on d.word_id = m.word_id
    ),
    listed as (
        select r.*
        from rated r
        where case p_status
                  when 'due' then r.is_due
                  when 'learning' then r.status = 'learning'
                  when 'known' then r.status = 'known'
              end
        order by case when p_status = 'due' then r.due_at end,
                 r.created_at desc, r.root
        limit greatest(p_limit, 1)
    )
    select jsonb_build_object(
        'language', (select language from settings),
        'counts', (select jsonb_build_object(
                       'known', count(*) filter (where status = 'known'),
                       'learning', count(*) filter (where status = 'learning'),
                       'due', count(*) filter (where is_due))
                   from rated),
        'words', coalesce((select jsonb_agg(jsonb_build_object(
                               'word', l.root, 'translation', l.translation,
                               'status', l.status, 'due', l.is_due)
                           order by case when p_status = 'due' then l.due_at end,
                                    l.created_at desc, l.root)
                           from listed l), '[]'::jsonb)
    );
$$;

revoke execute on function public.mcp_vocabulary(uuid, text, text, integer)
    from public, anon, authenticated;
grant execute on function public.mcp_vocabulary(uuid, text, text, integer) to service_role;
