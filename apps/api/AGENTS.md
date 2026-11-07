# apps/api: rules for agents

## AI calls cost money: they all go through `ai_gateway.py`

Every request to an AI provider (OpenRouter chat and Jev decisions, DeepInfra
Whisper, ElevenLabs speech) is made with a client from `ai_gateway.py`, and
names the feature that pays for it. Read that module's docstring before you
add, move or change any AI call.

- Use `chat(source, ...)`, `parse_structured(source, ...)`,
  `transcribe(source, ...)`, or `http_client(source)` /
  `async_http_client(source)` with `JEV_URL` / `CHAT_URL` for raw endpoints.
- Never build your own `httpx`/`requests`/`openai` client for an AI host,
  never name an AI host and never read an AI key outside `ai_gateway.py`.
- A new feature adds its source to `ai_gateway.SOURCES` (one line on what the
  user gets for the money) and a line to `FEATURES` in `test_ai_gateway.py`.
- In tests, request the `ai_upstream` fixture (`conftest.py`). Any test that
  reaches an AI host without the gateway, or calls the gateway without that
  fake, fails.

Where the money went: `python scripts/ai_spend.py --days 7 --by day,source`
(table `ai_spend`, `sql/ai_spend.sql`), or OpenRouter's Logs, where each
generation's `external_user` is its source. Check the OpenRouter balance
before any bulk run: production Jev shares the account.

## Tests and lint

    .venv/bin/python -m pytest -q
    .venv/bin/ruff check .
