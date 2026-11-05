-- word_rating: the thumbs on the extension's word popup (practice.rate_word).
--
-- A thumb is the user grading the word themselves, so unlike a ChatGPT
-- practice answer (srs_langfour_practice) a thumbs-up moves the card even when
-- it is not due: up is a 'good' review, down an 'again'. The event is a
-- word_events recall row (source 'extension', context.rating), and the
-- srs_outbox row records the result, so scoring counts it once and a second
-- rating of the card the same day finds it (practice.cards_practiced_since).
--
-- Requires langfour_provider.sql. HOW THIS GETS APPLIED: through the Supabase
-- connector, like the other files here. Idempotent.

create or replace function public.srs_langfour_rate(p_event_id bigint, p_outcome text)
returns public.srs_outbox
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_row public.srs_outbox;
    v_event public.word_events;
    v_card bigint;
    v_at timestamptz;
begin
    select * into v_row from public.srs_outbox where event_id = p_event_id;
    if found then
        return v_row;
    end if;
    select * into strict v_event from public.word_events where id = p_event_id;
    select c.id into v_card
      from public.srs_notes n join public.srs_cards c on c.note_id = n.id
     where n.user_id = v_event.user_id and n.word_id = v_event.word_id
       and n.provider = 'langfour'
       for update of c;

    v_at := public.srs_langfour_review(v_event.user_id, v_event.word_id, p_outcome = 'good');
    if v_at is null then
        v_row := row(p_event_id, v_card, p_outcome, 'skipped', now(), 'word_off', null);
    else
        v_row := row(p_event_id, v_card, p_outcome, 'applied', now(), null, v_at);
    end if;
    insert into public.srs_outbox select v_row.*;
    return v_row;
end;
$$;

revoke execute on function public.srs_langfour_rate(bigint, text) from public, anon, authenticated;
grant execute on function public.srs_langfour_rate(bigint, text) to service_role;
