-- srs_outbox: recalls from outside the flashcard systems that are on their way
-- to a flashcard.
--
-- A ChatGPT practice session (the MCP tool record_practice) writes one
-- word_events row per answer. For a word RemNote schedules, it also writes a
-- row here naming the card the answer applies to. The RemNote plugin collects
-- pending rows (GET /sync/remnote/inbox), adds the review to the card, and
-- reports back (POST /sync/remnote/practice): applied, with the date of the
-- review it added, or skipped, with the reason.
--
-- Separate from word_events because the log is append-only and this is not:
-- delivery moves from pending to applied or skipped. It also only has rows for
-- recalls meant for a card; exposures, which far outnumber recalls, never get
-- one.
--
-- Counting a recall once: an applied row's review arrives in srs_reviews
-- through the normal sync, keyed (card_id, applied_review_at). Scoring reads
-- srs_reviews plus word_events, minus the recall events whose row here is
-- 'applied'. RemNote itself can't tell these reviews apart (its SDK call takes
-- only a score), which is why only conservative grades are sent: 'again' for
-- a wrong answer, 'good' (never 'easy') for a right one.
--
-- Langfour-scheduled users get no rows until Langfour cards exist
-- (docs/plans/learner-word-data-model.md, step 3); their recalls are events
-- only.
--
-- Requires word_events.sql and remnote_sync.sql. HOW THIS GETS APPLIED:
-- through the Supabase connector, like the other files here. Idempotent.

create table if not exists public.srs_outbox (
    event_id          bigint primary key references public.word_events (id) on delete cascade,
    -- Null once the card is deleted (the Rem changed direction or was removed);
    -- the plugin skips such a row.
    card_id           bigint references public.srs_cards (id) on delete set null,
    outcome           text not null check (outcome in ('again', 'good')),
    status            text not null default 'pending'
                          check (status in ('pending', 'applied', 'skipped')),
    decided_at        timestamptz,
    reason            text,
    -- The repetition date RemNote recorded for the added review.
    applied_review_at timestamptz,
    check ((status = 'pending') = (decided_at is null)),
    check (status = 'applied' or applied_review_at is null)
);

create index if not exists srs_outbox_pending on public.srs_outbox (card_id)
    where status = 'pending';

alter table public.srs_outbox enable row level security;

-- Signed-in users read their own rows; writes go through the API only.
drop policy if exists srs_outbox_select_own on public.srs_outbox;
create policy srs_outbox_select_own on public.srs_outbox
    for select to authenticated
    using (exists (select 1 from public.word_events e
                   where e.id = event_id and e.user_id = (select auth.uid())));

revoke insert, update, delete, truncate on public.srs_outbox from anon, authenticated;
