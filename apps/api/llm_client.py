"""
Every LLM client in one place.

Chat completions go to OpenRouter, which speaks the OpenAI wire protocol — so
the official `openai` SDK works unchanged, pointed at a different base_url.
That is the whole trick; there is no OpenRouter-specific library.

    from llm_client import client
    from models import MODEL_SMART
    client.chat.completions.create(model=MODEL_SMART, ...)

TWO THINGS THAT ARE NOT OPENROUTER
----------------------------------
1. Audio transcription. OpenRouter proxies chat completions only; there is no
   /audio/transcriptions endpoint. Whisper therefore runs on DeepInfra, which
   does expose an OpenAI-compatible /audio/transcriptions route — so it is the
   same SDK again, pointed at a third base_url. Nothing in this repo calls
   OpenAI any more.

2. Strict structured output. Support varies by model and by the provider
   OpenRouter happens to route you to. parse_structured() below handles the
   variation rather than assuming.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Type, TypeVar

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

# Self-loading, exactly as supabase_client.py does. This module is imported
# via videoparsing on line 10 of app.py, which is before app.py's own
# load_dotenv() on line 14 -- so it cannot rely on another module having
# populated os.environ first.
load_dotenv()

log = logging.getLogger(__name__)

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

_api_key = os.getenv("OPENROUTER_API_KEY")
if not _api_key:
    raise RuntimeError(
        "OPENROUTER_API_KEY is not set. Chat completions now go through "
        "OpenRouter; see apps/api/.env.sample. This is raised at import time "
        "on purpose — the previous Azure setup failed here with an opaque "
        "error instead."
    )

# Optional, and only used for OpenRouter's public leaderboards. Harmless to omit.
_headers = {}
if os.getenv("OPENROUTER_SITE_URL"):
    _headers["HTTP-Referer"] = os.environ["OPENROUTER_SITE_URL"]
if os.getenv("OPENROUTER_APP_NAME"):
    _headers["X-Title"] = os.environ["OPENROUTER_APP_NAME"]

client = OpenAI(
    base_url=OPENROUTER_BASE_URL,
    api_key=_api_key,
    default_headers=_headers or None,
)


DEEPINFRA_BASE_URL = os.getenv("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai")


def transcription_client() -> OpenAI:
    """Whisper client, on DeepInfra.

    Built lazily rather than at import: only videoparsing.py transcribes, so
    the rest of the API runs without a DeepInfra key at all.
    """
    key = os.getenv("DEEPINFRA_API_KEY")
    if not key:
        raise RuntimeError(
            "DEEPINFRA_API_KEY is not set. It is needed only for audio "
            "transcription (videoparsing.py); OpenRouter cannot do this."
        )
    return OpenAI(base_url=DEEPINFRA_BASE_URL, api_key=key)


T = TypeVar("T", bound=BaseModel)


def parse_structured(
    *,
    model: str,
    messages: list[dict[str, Any]],
    schema_model: Type[T],
    reasoning: dict[str, Any] | None = None,
    **kwargs: Any,
) -> T:
    """Return a validated Pydantic object, replacing beta.chat.completions.parse.

    The SDK's .parse() helper is OpenAI-specific and assumes strict
    json_schema support. Across OpenRouter that assumption does not hold for
    every model and provider, so this tries the strict path first and falls
    back to plain JSON mode, validating with Pydantic either way. Validation
    is what actually guarantees the shape — the response_format is an
    optimisation, not the contract.
    """
    schema = schema_model.model_json_schema()
    schema["additionalProperties"] = False

    strict_format = {
        "type": "json_schema",
        "json_schema": {
            "name": schema_model.__name__,
            "strict": True,
            "schema": schema,
        },
    }

    # (response_format, reasoning override). The third attempt exists because
    # reasoning models spend max_tokens on reasoning before emitting any
    # content: deepseek-v4-flash burned 1203 reasoning tokens against a 1200
    # cap and returned an empty body. Raising the cap does not help -- the
    # reasoning expands to fill it -- so the rescue is to switch reasoning off,
    # which for a classification task is also 12-24x cheaper.
    attempts: list[tuple[dict[str, Any], dict[str, Any] | None]] = [
        (strict_format, reasoning),
        ({"type": "json_object"}, reasoning),
        (strict_format, {"enabled": False}),
    ]

    last_error: Exception | None = None
    for i, (response_format, reasoning_cfg) in enumerate(attempts):
        try:
            extra = dict(kwargs)
            if reasoning_cfg is not None:
                extra["extra_body"] = {**extra.get("extra_body", {}),
                                       "reasoning": reasoning_cfg}
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format=response_format,
                **extra,
            )
            choice = resp.choices[0]
            msg = choice.message
            if getattr(msg, "refusal", None):
                raise RuntimeError(f"Model refused: {msg.refusal}")

            content = (msg.content or "").strip()
            if not content:
                raise ValueError(
                    f"Empty response body (finish_reason={choice.finish_reason})"
                )
            # Some models wrap JSON in prose or a fenced block.
            start, end = content.find("{"), content.rfind("}")
            if start != -1 and end > start:
                content = content[start : end + 1]
            return schema_model.model_validate(json.loads(content))

        except Exception as exc:  # noqa: BLE001 - deliberately broad, we retry
            last_error = exc
            if i + 1 < len(attempts):
                log.warning(
                    "structured output via %s failed (%s); retrying with %s",
                    response_format["type"], exc, attempts[i + 1][0]["type"],
                )

    raise RuntimeError(f"Structured output failed for {model}: {last_error}")


__all__ = [
    "client",
    "transcription_client",
    "parse_structured",
    "OPENROUTER_BASE_URL",
    "DEEPINFRA_BASE_URL",
]
