-- pending_words: unknown transcript tokens that parse() did not attach.
--
-- parse() asks Jev which existing root an unknown token is a form of
-- (word_matching.py). A confident pick becomes a wordform; everything else
-- lands here instead of creating a root while a transcript waits:
--   pending     Jev chose none of the candidates, or was unsure
--   not_a_word  Jev was close to certain the token is not a word; kept so the
--               cutoff can be checked, never linked
-- A later batch job decides these (new root, form of a root, or junk) and
-- sets resolved_at. One row per token and language; `seen` counts how many
-- transcripts hit it, so frequent tokens can go first.
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector, like the
-- other files here. Idempotent. Only the API's service role writes it.

create table if not exists public.pending_words (
    language    text not null check (language in ('es', 'de', 'it', 'fr')),
    word        text not null,
    outcome     text not null check (outcome in ('pending', 'not_a_word')),
    source      text,                 -- first video or article it came from
    candidates  text[] not null default '{}',
    jev         jsonb,                -- raw answers, to re-tune thresholds
    seen        integer not null default 1,
    created_at  timestamptz not null default now(),
    resolved_at timestamptz,
    primary key (language, word)
);

alter table public.pending_words enable row level security;
-- RLS without policies already keeps anon and authenticated out; drop their
-- default grants too, so turning RLS off would not expose the table.
revoke all on public.pending_words from anon, authenticated;

create or replace function public.record_pending_words(rows jsonb)
returns void
language sql
security invoker
set search_path = ''
as $$
  insert into public.pending_words (language, word, outcome, source, candidates, jev)
  select r->>'language', r->>'word', r->>'outcome', r->>'source',
         array(select jsonb_array_elements_text(r->'candidates')), r->'jev'
  from jsonb_array_elements(rows) r
  on conflict (language, word) do update
     set seen = public.pending_words.seen + 1;
$$;

revoke all on function public.record_pending_words(jsonb) from public, anon, authenticated;
grant execute on function public.record_pending_words(jsonb) to service_role;
