-- userdata.chatgpt_language_check: per-account switch for the ChatGPT
-- highlighter's language check (language_check.py).
--
-- When it is on, the highlighter asks the API, per paragraph, which of the
-- words it would mark are in the language being learned in that spot, so
-- Spanish words inside English text ("gave me", "by bus", "Irregular forms:")
-- stay unmarked. Off by default: each check is a Jev request.
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector, like the
-- other files here. Idempotent.

alter table public.userdata
    add column if not exists chatgpt_language_check boolean not null default false;
