-- RemNote sync: RemNote owns scheduling, Langfour records what happened.
--
-- The RemNote plugin (apps/remnote-plugin) creates one Rem per learning word
-- and reports back which Rem and cards it made and every review RemNote
-- recorded. Langfour's own SM-2 columns on userwords are left alone: for a
-- user whose review_provider is 'remnote' they simply stop being written.
--
-- Why three tables instead of columns on userwords: the facts have different
-- cardinalities. A word has at most one Rem per provider, a Rem has one card
-- per direction (forward, backward, or a cloze), and a card has many reviews.
-- Flattening that onto userwords would mean either one card's worth of state
-- per word or arrays in columns. Reviews are stored as events, not as derived
-- numbers (interval, lapses, ease): those are computed from the events when a
-- definition of "learned" is settled, and can be redefined without resyncing.
-- The one piece of state that cannot be derived is RemNote's next due date,
-- which depends on RemNote's scheduler, so it lives on the card.
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector, like
-- video_queue.sql. Idempotent: safe to re-run.

-- ---------------------------------------------------------------------------
-- Who schedules reviews for a user. A property of the user, so it belongs on
-- userdata. 'remnote' hides Langfour's review session in the web app.
-- ---------------------------------------------------------------------------
alter table public.userdata
    add column if not exists review_provider text not null default 'langfour';

alter table public.userdata drop constraint if exists userdata_review_provider_check;
alter table public.userdata add constraint userdata_review_provider_check
    check (review_provider in ('langfour', 'remnote'));

-- The user's top-level "Langfour" document in RemNote, reported by the plugin
-- on every full sync. The web app and the extension link to its flashcard
-- queue (https://www.remnote.com/flashcards/<id>), which reviews every
-- Langfour card. Null until the plugin has synced once.
alter table public.userdata
    add column if not exists remnote_root_rem_id text;

alter table public.userdata drop constraint if exists userdata_remnote_root_rem_id_check;
alter table public.userdata add constraint userdata_remnote_root_rem_id_check
    check (remnote_root_rem_id ~ '^[A-Za-z0-9_-]{1,64}$');

-- ---------------------------------------------------------------------------
-- Personal access tokens. The RemNote plugin cannot hold a Supabase session,
-- so the web app issues a long-lived token, shown once, stored only as a
-- SHA-256 hash. `purpose` limits what a token can reach: auth.py accepts a
-- 'remnote_sync' token on /sync/remnote/* and nowhere else.
-- ---------------------------------------------------------------------------
create table if not exists public.api_tokens (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users (id) on delete cascade,
    purpose      text not null check (purpose in ('remnote_sync')),
    token_hash   text not null unique,
    created_at   timestamptz not null default now(),
    last_used_at timestamptz,
    revoked_at   timestamptz
);

-- One live token per user and purpose; issuing a new one revokes the old.
create unique index if not exists api_tokens_one_active
    on public.api_tokens (user_id, purpose)
    where revoked_at is null;

-- No policies: only the API (service_role) reads or writes tokens.
alter table public.api_tokens enable row level security;

-- ---------------------------------------------------------------------------
-- Pairings: how the plugin gets its token without anyone copying it. The
-- plugin opens a pairing and keeps its secret (only the hash is stored); the
-- signed-in user approves the short user_code in the web app, which sets
-- user_id; the plugin then exchanges the secret for a token and the row is
-- deleted. Rows expire after ten minutes whether or not they were used.
-- ---------------------------------------------------------------------------
create table if not exists public.api_token_pairings (
    id          uuid primary key default gen_random_uuid(),
    purpose     text not null check (purpose in ('remnote_sync')),
    secret_hash text not null unique,
    user_code   text not null unique,       -- e.g. KFPM-2931, shown on both screens
    user_id     uuid references auth.users (id) on delete cascade,  -- set on approval
    approved_at timestamptz,
    created_at  timestamptz not null default now(),
    expires_at  timestamptz not null
);

-- No policies: only the API (service_role) reads or writes pairings.
alter table public.api_token_pairings enable row level security;

-- ---------------------------------------------------------------------------
-- srs_notes: which Rem holds which of the user's words.
-- ---------------------------------------------------------------------------
create table if not exists public.srs_notes (
    id          bigint generated always as identity primary key,
    user_id     uuid not null,
    word_id     integer not null,
    provider    text not null check (provider in ('remnote')),
    external_id text not null,               -- RemNote Rem _id
    created_at  timestamptz not null default now(),
    -- Set when the Rem disappears from RemNote. The row is kept so the word
    -- is not offered to the plugin again: deleting a card is a decision.
    removed_at  timestamptz,
    -- Composite FK: a note can only exist for a word the user actually has.
    -- Removing the word from Langfour removes its sync history with it.
    foreign key (user_id, word_id)
        references public.userwords (user_id, word_id) on delete cascade,
    unique (user_id, provider, word_id),
    unique (user_id, provider, external_id)
);

-- ---------------------------------------------------------------------------
-- srs_cards: the cards RemNote generated from a note.
-- ---------------------------------------------------------------------------
create table if not exists public.srs_cards (
    id          bigint generated always as identity primary key,
    note_id     bigint not null references public.srs_notes (id) on delete cascade,
    external_id text not null,               -- RemNote Card _id
    kind        text not null check (kind in ('forward', 'backward', 'cloze')),
    next_due_at timestamptz,                 -- null until RemNote schedules it
    unique (note_id, external_id)
);

-- ---------------------------------------------------------------------------
-- srs_reviews: one row per graded review. RemNote's non-grading events (too
-- early, reset, manual date/ease, leech) and cram reviews do not move the
-- schedule and are not recorded.
-- ---------------------------------------------------------------------------
create table if not exists public.srs_reviews (
    card_id     bigint not null references public.srs_cards (id) on delete cascade,
    reviewed_at timestamptz not null,
    outcome     text not null check (outcome in ('again', 'hard', 'good', 'easy')),
    -- The plugin resends an overlapping window of history on every sync, so
    -- the primary key doubles as the idempotency key.
    primary key (card_id, reviewed_at)
);

-- ---------------------------------------------------------------------------
-- srs_sync_leases: at most one sync run per user at a time, across devices.
-- Two concurrent runs would both be handed the same pending words and both
-- create a Rem for each. A run renews its lease on every request; a run that
-- dies lets it lapse after the TTL the API passes (remnote_sync.LEASE_SECONDS).
-- ---------------------------------------------------------------------------
create table if not exists public.srs_sync_leases (
    user_id    uuid primary key references auth.users (id) on delete cascade,
    holder     text not null,          -- the plugin's id for this sync run
    expires_at timestamptz not null
);

-- No policies: only the API (service_role) touches leases.
alter table public.srs_sync_leases enable row level security;

-- Take or renew the lease in one statement, so two runs cannot both win: the
-- conditional DO UPDATE only fires for the current holder or an expired
-- lease, and RETURNING is empty when it does not. Takes the user id because
-- only the API calls it; execute is revoked from every client role.
create or replace function public.srs_acquire_sync_lease(
    p_user_id uuid, p_holder text, p_seconds integer
) returns boolean
language sql
security invoker
set search_path = ''
as $$
    with granted as (
        insert into public.srs_sync_leases as l (user_id, holder, expires_at)
        values (p_user_id, p_holder, now() + make_interval(secs => p_seconds))
        on conflict (user_id) do update
            set holder = excluded.holder, expires_at = excluded.expires_at
            where l.holder = excluded.holder or l.expires_at < now()
        returning 1
    )
    select exists (select 1 from granted);
$$;

revoke execute on function public.srs_acquire_sync_lease(uuid, text, integer)
    from public, anon, authenticated;
grant execute on function public.srs_acquire_sync_lease(uuid, text, integer)
    to service_role;

-- The FK lookups Postgres does not index on its own.
create index if not exists srs_cards_note on public.srs_cards (note_id);

-- ---------------------------------------------------------------------------
-- RLS. Writes happen only through the API (service_role). Signed-in users may
-- read their own rows, so the web app can show progress without a new
-- endpoint for every view.
-- ---------------------------------------------------------------------------
alter table public.srs_notes   enable row level security;
alter table public.srs_cards   enable row level security;
alter table public.srs_reviews enable row level security;

drop policy if exists srs_notes_select_own on public.srs_notes;
create policy srs_notes_select_own on public.srs_notes
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists srs_cards_select_own on public.srs_cards;
create policy srs_cards_select_own on public.srs_cards
    for select to authenticated
    using (exists (select 1 from public.srs_notes n
                   where n.id = note_id and n.user_id = (select auth.uid())));

drop policy if exists srs_reviews_select_own on public.srs_reviews;
create policy srs_reviews_select_own on public.srs_reviews
    for select to authenticated
    using (exists (select 1 from public.srs_cards c
                   join public.srs_notes n on n.id = c.note_id
                   where c.id = card_id and n.user_id = (select auth.uid())));

-- ---------------------------------------------------------------------------
-- Disabled in RemNote. Turning a Rem's flashcards off there means "stop
-- practising this word", so the sync moves a learning word to 'disabled' and
-- turning the cards back on returns it to 'learning'. A status rather than a
-- deleted row: deleting would cascade through srs_notes to the word's cards
-- and review history, and the word would be offered again as new. A known
-- word stays known; only learning <-> disabled is synced (apps/api/remnote_sync.py).
--
-- 'disabled' is neither learning nor known: user_known_words already looks
-- only at those two, and the two list readers below now leave it out.
-- (Applied as migration userwords_disabled_status, which also changed the
-- uncalled get_learning_and_unknown_words to filter on status = 'learning'.)
-- ---------------------------------------------------------------------------
alter table public.userwords drop constraint if exists userwords_status_check;
alter table public.userwords add constraint userwords_status_check
    check (status in ('learning', 'known', 'disabled'));

create or replace function public.get_learning_words(order_direction text, cursor_word_id integer, search_term text, page_size integer, language_filter text, source_filter text)
 returns table(word_id integer, word text, translation text, status text, review_due text, source text)
 language plpgsql
 set search_path to 'public', 'pg_temp'
as $function$
BEGIN
  RETURN QUERY
  WITH flashcard_correct_tests AS (
    SELECT
      ft.word_id,
      COUNT(*) AS correct_count
    FROM FlashcardTests ft
    WHERE ft.user_id = auth.uid()::uuid
      AND ft.test_result = true
    GROUP BY ft.word_id
  ),
  user_words_with_status AS (
    SELECT
      uw.word_id,
      w.root                AS word,
      COALESCE(ut.custom_translation, w.translation) AS translation,
      (
        CASE
          WHEN uw.status = 'known' THEN 'known'
          WHEN uw.status = 'learning'
               AND COALESCE(fc.correct_count, 0) > 0
            THEN CAST(fc.correct_count AS text)
          WHEN uw.status = 'learning' THEN 'new'
          ELSE uw.status
        END
      )::text              AS status,
      uw.next_review_due_at,
      COALESCE(fc.correct_count, 0) AS correct_count,
      uw.source            AS source
    FROM UserWords uw
    JOIN words w
      ON uw.word_id = w.id
    LEFT JOIN UserTranslations ut
      ON uw.word_id = ut.word_id
      AND uw.user_id = ut.user_id
    LEFT JOIN flashcard_correct_tests fc
      ON uw.word_id = fc.word_id
    WHERE uw.user_id = auth.uid()::uuid
      AND (language_filter IS NULL OR w.language = language_filter)
      AND (source_filter   IS NULL OR uw.source = source_filter)
      AND (
        (order_direction = 'DESC' AND uw.word_id < cursor_word_id)
        OR (order_direction <> 'DESC' AND uw.word_id > cursor_word_id)
        OR cursor_word_id = 0
      )
      AND (
        search_term IS NULL
        OR w.root ILIKE '%' || search_term || '%'
        OR COALESCE(ut.custom_translation, w.translation) ILIKE '%' || search_term || '%'
      )
  )
  SELECT
    uws.word_id,
    uws.word,
    uws.translation,
    uws.status,
    CASE
      WHEN uws.next_review_due_at::date = CURRENT_DATE THEN 'due today'
      WHEN uws.next_review_due_at IS NULL            THEN 'no review date'
      ELSE (uws.next_review_due_at::date - CURRENT_DATE)::text
    END AS review_due,
    uws.source
  FROM user_words_with_status uws
  WHERE uws.status NOT IN ('known', 'disabled')
  ORDER BY
    (uws.status <> 'new') DESC,
    CASE WHEN order_direction = 'DESC' THEN uws.word_id END DESC,
    CASE WHEN order_direction = 'ASC'  OR order_direction IS NULL THEN uws.word_id END ASC
  FETCH NEXT page_size ROWS ONLY;
END;
$function$;

create or replace function public.get_userwords_filtered(language_filter text, due_type text, page_size integer, p_source text default null::text)
 returns table(word_id integer, word_root text, translation text, next_review_due_at timestamp without time zone)
 language plpgsql
 set search_path to 'public', 'pg_temp'
as $function$
BEGIN
    RETURN QUERY
    SELECT
        uw.word_id,
        w.root AS word_root,
        COALESCE(ut.custom_translation, w.translation) AS translation,
        uw.next_review_due_at
    FROM userwords            AS uw
    JOIN words                AS w  ON uw.word_id = w.id
    LEFT JOIN usertranslations ut
           ON ut.word_id = w.id
          AND ut.user_id = auth.uid()
    WHERE uw.user_id = auth.uid()
      AND uw.status <> 'disabled'
      AND w.language = language_filter
      AND (p_source IS NULL OR uw.source = p_source)     -- ← only filters if supplied
      AND (
            (due_type = 'today'   AND uw.next_review_due_at::date = CURRENT_DATE) OR
            (due_type = 'overdue' AND uw.next_review_due_at <  CURRENT_DATE)      OR
            (due_type = 'both'    AND (uw.next_review_due_at < CURRENT_DATE
                                    OR  uw.next_review_due_at::date = CURRENT_DATE))
          )
    ORDER BY uw.next_review_due_at
    FETCH NEXT page_size ROWS ONLY;
END;
$function$;
