-- ai_spend: what each feature spends on AI, per hour (ai_gateway.py).
--
-- Every AI request in apps/api goes through ai_gateway, which names the
-- feature that pays for it (its "source", registered in ai_gateway.SOURCES)
-- and reads the cost the provider returns. Each process sums its calls per
-- (hour, origin, source, provider, model) and adds the sums here once a
-- minute through record_ai_spend(). One row per key per hour: a few hundred a
-- day, where per-call rows would be ~170k on a busy Jev day.
--
--   origin        the process: "uvicorn" on Koyeb, or a script's file name
--   source        the feature (ai_gateway.SOURCES)
--   provider      openrouter | deepinfra | elevenlabs
--   cost_usd      as the provider reported it. DeepInfra's transcription
--                 reply has no cost, so Whisper shows calls and $0
--   input_tokens  for ElevenLabs, characters (what it bills)
--   errors        calls answered 4xx/5xx (402 = out of credit)
--
-- Read it with `python scripts/ai_spend.py --days 7`, or:
--   select source, sum(calls), round(sum(cost_usd)::numeric, 4) as usd
--   from ai_spend where hour > now() - interval '1 day'
--   group by 1 order by 3 desc;
--
-- Service role only: RLS on, no policies.
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector, like
-- video_queue.sql. Idempotent: safe to re-run. Until it is applied the
-- gateway logs each flush and a warning that the write failed; nothing breaks.

create table if not exists public.ai_spend (
    hour          timestamptz not null,
    origin        text        not null,
    source        text        not null,
    provider      text        not null,
    model         text        not null default '',
    calls         bigint      not null default 0,
    input_tokens  bigint      not null default 0,
    output_tokens bigint      not null default 0,
    cost_usd      double precision not null default 0,
    errors        bigint      not null default 0,
    primary key (hour, origin, source, provider, model)
);

create index if not exists ai_spend_source_hour on public.ai_spend (source, hour desc);

alter table public.ai_spend enable row level security;

-- Adds a batch of sums to the table: existing rows grow, new ones appear.
create or replace function public.record_ai_spend(rows jsonb)
returns void
language sql
security invoker
set search_path = public
as $$
    insert into public.ai_spend as s
        (hour, origin, source, provider, model, calls, input_tokens, output_tokens, cost_usd, errors)
    select (r->>'hour')::timestamptz, r->>'origin', r->>'source', r->>'provider',
           coalesce(r->>'model', ''), (r->>'calls')::bigint, (r->>'input_tokens')::bigint,
           (r->>'output_tokens')::bigint, (r->>'cost_usd')::double precision,
           (r->>'errors')::bigint
    from jsonb_array_elements(rows) as r
    on conflict (hour, origin, source, provider, model) do update set
        calls         = s.calls + excluded.calls,
        input_tokens  = s.input_tokens + excluded.input_tokens,
        output_tokens = s.output_tokens + excluded.output_tokens,
        cost_usd      = s.cost_usd + excluded.cost_usd,
        errors        = s.errors + excluded.errors;
$$;

revoke all on function public.record_ai_spend(jsonb) from public, anon, authenticated;
grant execute on function public.record_ai_spend(jsonb) to service_role;
