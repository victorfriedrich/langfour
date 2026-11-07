"""
The one door to every paid AI API, and the record of what each feature spends.

READ THIS BEFORE ADDING OR CHANGING ANY AI CALL
-----------------------------------------------
Every request to OpenRouter (chat completions and Jev's Decisions API),
DeepInfra (Whisper) and ElevenLabs (speech) is made with a client built in
this module, and names a SOURCE: the feature that pays for it. Nothing else in
apps/api names an AI host, reads an AI key or imports `openai`.
test_ai_gateway.py fails the build when that slips, and every API test fails
if it makes an AI request that did not come through here.

    from ai_gateway import chat, parse_structured, transcribe, http_client, JEV_URL

    chat("reader.translate_section", model=MODEL_FAST, messages=[...])
    parse_structured("parse.word_root", model=..., messages=..., schema_model=Root)
    transcribe("video.transcribe", model=MODEL_TRANSCRIBE, file=fh, ...)
    with http_client("video.quality", timeout=60) as http:    # raw endpoints:
        http.post(JEV_URL, json={...})                        # Jev, vision chat
    async with async_http_client("words.importance") as http: ...

A new feature adds its source to SOURCES below, one line saying what the user
gets for the money. An unregistered source raises, so the spend breakdown
never has an "other" bucket.

WHY
---
OpenRouter's dashboard showed one key and the app "Unknown" for every
request, so a $7 day could not be traced to the code that caused it. Now:

1. OpenRouter sees the source. Every OpenRouter request body (chat and Jev)
   carries user=<source>, which OpenRouter keeps per generation as
   `external_user`: private, and filterable in its Logs. (A per-source
   HTTP-Referer would register a public app per feature, so there is none.)
2. The gateway reads the cost OpenRouter returns with every response
   (`usage.cost`), sums it per (hour, origin, source, provider, model) and
   writes the sums to Supabase every minute: table `ai_spend`
   (sql/ai_spend.sql). `origin` is the process: "uvicorn" on Koyeb, or the
   script's file name. `python scripts/ai_spend.py --days 7` reads it.
3. Each flush also logs one INFO line per source, so Koyeb's logs carry the
   same numbers when the table is unreachable.

PROVIDER NOTES
--------------
OpenRouter speaks the OpenAI wire protocol, so the `openai` SDK is used
unchanged, pointed at a different base_url. It proxies chat completions only:
Whisper runs on DeepInfra, which has an OpenAI-compatible
/audio/transcriptions route, so that is the same SDK at a third base_url.
DeepInfra's text response carries no usage, so transcription is counted in
calls, not dollars. ElevenLabs bills characters; those are recorded as input
tokens.

Strict structured output varies by model and by the provider OpenRouter
routes to; parse_structured() below handles the variation.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import httpx
from dotenv import load_dotenv
from openai import AuthenticationError, OpenAI, PermissionDeniedError
from pydantic import BaseModel

# Self-loading, exactly as supabase_client.py does: this module is imported
# (via videoparsing) before app.py's own load_dotenv().
load_dotenv()

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sources: every feature that spends money on AI, and what it buys.
# ---------------------------------------------------------------------------

SOURCES: dict[str, str] = {
    # Dictionary growth while parsing text (nlp_processing.parse and friends)
    "parse.attach_word": "Jev attaches an unknown token to an existing root (word_matching.py)",
    "parse.word_root": "LLM finds the root of a new word (nlp_processing.get_word_root)",
    "parse.alternatives": "LLM lists a new root's forms (nlp_processing.generate_alternatives)",
    "parse.verify_translate": "LLM checks and translates a new root (nlp_processing.verify_and_translate)",
    "parse.verify_language": "LLM drops words not in the language (nlp_processing.verify_language)",
    "parse.filter_entities": "LLM strips names from a transcript (nlp_processing.filter_entities)",
    "translate_word": "LLM translates a dictionary word with no translation (database.get_or_create_translation)",
    # Reader and Library
    "reader.translate_section": "Translate a reader section on request (/api/translate)",
    "reader.summarize": "Title for an imported article (nlp_processing.summarize_text)",
    "reader.word_examples": "Example sentences for a word (nlp_processing.generate_word_examples)",
    "reader.language_check": "Jev keeps only in-language words when marking ChatGPT replies (language_check.py)",
    "words.importance": "Jev ranks a text's key words on first open (word_importance.py)",
    "words.familiarity": "Jev rates which missing words a learner can work out (word_familiarity.py)",
    "tts": "ElevenLabs pronunciation for word popups (tts.py)",
    # Video corpus
    "video.transcribe": "Whisper transcribes a video without captions (videoparsing.whisper)",
    "video.quality": "Jev rates a transcript for recommendation (video_quality.py)",
    "video.category": "Jev picks a video's browse topic (video_category.py)",
    "video.looks": "Vision model judges a thumbnail (video_looks.py)",
    "pipeline.channel_verdict": "LLM rates a discovered channel's sensitivity (ytpipeline.verdict_for)",
    "pipeline.channel_judge": "Jev judges a discovered channel's worth (ytpipeline.judge)",
    # One-off and maintenance scripts (apps/api/scripts)
    "script.audit_words": "Jev audits dictionary entries (scripts/audit_words.py)",
    "script.cognates": "LLM marks cognates (scripts/cognates.py)",
    "script.language_flagging": "LLM flags words not in the language (scripts/language_flagging.py)",
    "script.language_updating": "LLM fills missing translations (scripts/language_updating.py)",
    "script.check_llm": "Smoke test of the LLM setup (scripts/check_llm.py)",
    "script.check_transcribe": "Smoke test of transcription (scripts/check_transcribe.py)",
    "script.listening_benchmark": "Whisper model comparison (scripts/listening_benchmark.py)",
}


class UnknownSource(ValueError):
    """The call named a source that is not in SOURCES."""


class MissingSource(RuntimeError):
    """A request reached an AI host through the gateway without a source."""


def _check(source: str) -> str:
    if source not in SOURCES:
        raise UnknownSource(
            f"AI source {source!r} is not registered. Add it to SOURCES in "
            "apps/api/ai_gateway.py with one line on what it buys.")
    return source


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEEPINFRA_BASE_URL = os.getenv("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai")

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
JEV_URL = "https://openrouter.ai/api/alpha/decisions"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

# Hosts that bill us. The test guard in conftest.py blocks these unless the
# request came through the gateway.
AI_HOSTS: dict[str, str] = {
    "openrouter.ai": "openrouter",
    "api.deepinfra.com": "deepinfra",
    "api.elevenlabs.io": "elevenlabs",
}

# The SDK default is 600s. These calls sit on the request path (a word lookup
# blocks a user), so a stalled connection is indistinguishable from a hang. A
# minute is far above the ~11s a slow classification takes.
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

# Optional app attribution. OpenRouter registers an app for a Referer (and
# may list it publicly), so it stays opt-in; the per-feature tag is the
# private `user` field instead (see _prepare).
SITE_URL = os.getenv("OPENROUTER_SITE_URL", "").rstrip("/")
APP_NAME = os.getenv("OPENROUTER_APP_NAME", "Langfour")

if not os.getenv("OPENROUTER_API_KEY"):
    # Raised at import on purpose: the API cannot boot without it, and an
    # opaque failure on the first request is worse.
    raise RuntimeError(
        "OPENROUTER_API_KEY is not set. Chat completions and Jev go through "
        "OpenRouter; see apps/api/.env.sample.")


def _auth_headers(provider: str) -> dict[str, str]:
    if provider == "openrouter":
        return {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}
    if provider == "deepinfra":
        key = os.getenv("DEEPINFRA_API_KEY")
        if not key:
            raise RuntimeError(
                "DEEPINFRA_API_KEY is not set. It is needed only for audio "
                "transcription (videoparsing.py); OpenRouter cannot do this.")
        return {"Authorization": f"Bearer {key}"}
    if provider == "elevenlabs":
        key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")
        return {"xi-api-key": key}
    raise ValueError(f"unknown AI provider {provider!r}")


def elevenlabs_configured() -> bool:
    return bool(os.getenv("ELEVENLABS_API_KEY", "").strip())


# ---------------------------------------------------------------------------
# The ledger: what each source spent
# ---------------------------------------------------------------------------

# The process, so a backfill script's spend is not mistaken for the app's.
ORIGIN = os.getenv("AI_SPEND_ORIGIN") or os.path.basename(sys.argv[0] or "") or "python"


@dataclass(frozen=True)
class Call:
    source: str
    provider: str
    model: str | None
    status: int
    input_tokens: int
    output_tokens: int
    cost: float | None   # USD, as the provider reported it; None when it does not
    generation_id: str | None
    ms: int


class Ledger:
    """Sums calls per (hour, origin, source, provider, model) and flushes the
    sums. Per-call rows would be ~170k a day at Jev's busiest; the sums are a
    few hundred."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._totals: dict[tuple[str, str, str, str, str], list[float]] = {}
        self.listeners: list[Callable[[Call], None]] = []
        self._flusher: threading.Thread | None = None

    def add(self, call: Call) -> None:
        hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0).isoformat()
        key = (hour, ORIGIN, call.source, call.provider, call.model or "")
        with self._lock:
            t = self._totals.setdefault(key, [0, 0, 0, 0.0, 0])
            t[0] += 1
            t[1] += call.input_tokens
            t[2] += call.output_tokens
            t[3] += call.cost or 0.0
            t[4] += 1 if call.status >= 400 else 0
        log.debug("ai call %s %s %s status=%s in=%s out=%s cost=%s gen=%s %sms",
                  call.source, call.provider, call.model, call.status, call.input_tokens,
                  call.output_tokens, call.cost, call.generation_id, call.ms)
        for listener in list(self.listeners):
            listener(call)
        self._start_flusher()

    def _start_flusher(self) -> None:
        if self._flusher is not None:
            return
        interval = float(os.getenv("AI_SPEND_FLUSH_SECONDS", "60"))
        if interval <= 0:
            return
        with self._lock:
            if self._flusher is not None:
                return

            def loop() -> None:
                while True:
                    time.sleep(interval)
                    self.flush()

            self._flusher = threading.Thread(target=loop, name="ai-spend-flush", daemon=True)
            self._flusher.start()
            atexit.register(self.flush)

    def take(self) -> list[dict[str, Any]]:
        with self._lock:
            totals, self._totals = self._totals, {}
        return [{"hour": h, "origin": o, "source": s, "provider": p, "model": m,
                 "calls": int(t[0]), "input_tokens": int(t[1]), "output_tokens": int(t[2]),
                 "cost_usd": round(t[3], 6), "errors": int(t[4])}
                for (h, o, s, p, m), t in totals.items()]

    def restore(self, rows: list[dict[str, Any]]) -> None:
        """Put back sums a failed write took, so the next flush retries them.
        Sums older than a day are dropped: the log line already has them, and
        a table that stays unreachable must not grow memory forever."""
        cutoff = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        with self._lock:
            for r in rows:
                if r["hour"] < cutoff:
                    continue
                key = (r["hour"], r["origin"], r["source"], r["provider"], r["model"])
                t = self._totals.setdefault(key, [0, 0, 0, 0.0, 0])
                t[0] += r["calls"]
                t[1] += r["input_tokens"]
                t[2] += r["output_tokens"]
                t[3] += r["cost_usd"]
                t[4] += r["errors"]

    def flush(self) -> None:
        rows = self.take()
        if not rows:
            return
        by_source: dict[str, list[float]] = {}
        for r in rows:
            s = by_source.setdefault(r["source"], [0, 0.0])
            s[0] += r["calls"]
            s[1] += r["cost_usd"]
        log.info("ai spend (%s): %s", ORIGIN, "; ".join(
            f"{src} {int(n)} calls ${cost:.4f}"
            for src, (n, cost) in sorted(by_source.items(), key=lambda kv: -kv[1][1])))
        try:
            _write(rows)
        except Exception as exc:   # retried next flush; the log line is the fallback
            log.warning("ai spend: could not write %d rows to ai_spend, retrying "
                        "next flush: %s", len(rows), exc)
            self.restore(rows)


def _write_supabase(rows: list[dict[str, Any]]) -> None:
    from supabase_client import supabase  # lazy: scripts may run without Supabase
    supabase.rpc("record_ai_spend", {"rows": rows}).execute()


def _write_log_only(rows: list[dict[str, Any]]) -> None:
    pass


_write: Callable[[list[dict[str, Any]]], None] = (
    _write_log_only if os.getenv("AI_SPEND_SINK", "supabase") == "log" else _write_supabase)

ledger = Ledger()


# ---------------------------------------------------------------------------
# The metered transport: every gateway client sends through this
# ---------------------------------------------------------------------------

SOURCE_HEADER = "x-langfour-source"
MODEL_HEADER = "x-langfour-model"   # for bodies the transport cannot read (multipart)

# Tests swap the real network for a fake one here (see conftest.ai_upstream).
_test_upstream: httpx.MockTransport | None = None


@dataclass
class _Outgoing:
    provider: str | None     # None: not an AI host (a thumbnail, say)
    source: str | None
    model_hint: str | None
    sent: dict[str, Any]     # the JSON body, parsed once


def _prepare(request: httpx.Request) -> tuple[httpx.Request, _Outgoing]:
    """Strip the gateway's own headers and tag an OpenRouter request with its
    source: `user=<source>` in the body, which OpenRouter keeps privately per
    generation (external_user). A Referer is sent only when
    OPENROUTER_SITE_URL is set, because OpenRouter registers an app for it."""
    source = request.headers.pop(SOURCE_HEADER, None)
    model_hint = request.headers.pop(MODEL_HEADER, None)
    provider = AI_HOSTS.get(request.url.host)
    if provider is None:
        return request, _Outgoing(None, source, model_hint, {})
    if not source:
        raise MissingSource(f"{request.method} {request.url} has no AI source")
    _check(source)
    sent: dict[str, Any] = {}
    if request.method == "POST" and "json" in request.headers.get("content-type", ""):
        with contextlib.suppress(ValueError):
            parsed = json.loads(request.content or b"{}")
            sent = parsed if isinstance(parsed, dict) else {}
    if provider == "openrouter":
        if SITE_URL:
            request.headers["HTTP-Referer"] = SITE_URL
            request.headers["X-Title"] = APP_NAME
        if sent and sent.get("user") != source:
            sent["user"] = source
            request = httpx.Request(
                request.method, request.url, json=sent, extensions=request.extensions,
                headers=[(k, v) for k, v in request.headers.multi_items()
                         if k.lower() != "content-length"])
    return request, _Outgoing(provider, source, model_hint, sent)


def _record(out: _Outgoing, request: httpx.Request, response: httpx.Response,
            started: float) -> None:
    if request.method != "POST" or not out.provider or not out.source:
        return   # credit checks, thumbnails: nothing billed
    body: dict[str, Any] = {}
    if "json" in response.headers.get("content-type", ""):
        with contextlib.suppress(ValueError):
            parsed = response.json()
            body = parsed if isinstance(parsed, dict) else {}
    sent = out.sent
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    inp = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    done = usage.get("completion_tokens") or usage.get("output_tokens") or 0
    if out.provider == "elevenlabs":
        inp = len(sent.get("text") or "")   # ElevenLabs bills characters
    ledger.add(Call(
        source=out.source, provider=out.provider,
        model=out.model_hint or sent.get("model") or sent.get("model_id") or body.get("model"),
        status=response.status_code, input_tokens=int(inp), output_tokens=int(done),
        cost=usage.get("cost"),
        generation_id=body.get("id") or response.headers.get("x-generation-id"),
        ms=int((time.monotonic() - started) * 1000)))


def _streams(response: httpx.Response) -> bool:
    return "event-stream" in response.headers.get("content-type", "")


class _Metered(httpx.BaseTransport):
    def __init__(self, **transport_kwargs: Any) -> None:
        self._real = httpx.HTTPTransport(**transport_kwargs)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request, out = _prepare(request)
        started = time.monotonic()
        upstream = _test_upstream if _test_upstream is not None else self._real
        response = upstream.handle_request(request)
        if out.provider and not _streams(response):
            response.read()
            _record(out, request, response, started)
        return response

    def close(self) -> None:
        self._real.close()


class _AsyncMetered(httpx.AsyncBaseTransport):
    def __init__(self, **transport_kwargs: Any) -> None:
        self._real = httpx.AsyncHTTPTransport(**transport_kwargs)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request, out = _prepare(request)
        started = time.monotonic()
        upstream = _test_upstream if _test_upstream is not None else self._real
        response = await upstream.handle_async_request(request)
        if out.provider and not _streams(response):
            await response.aread()
            _record(out, request, response, started)
        return response

    async def aclose(self) -> None:
        await self._real.aclose()


# ---------------------------------------------------------------------------
# Raw HTTP clients (Jev, vision chat, ElevenLabs)
# ---------------------------------------------------------------------------

def http_client(source: str, *, provider: str = "openrouter", timeout: float = 60,
                limits: httpx.Limits | None = None) -> httpx.Client:
    """An httpx.Client whose AI requests are attributed to `source`."""
    _check(source)
    kwargs = {"limits": limits} if limits else {}
    return httpx.Client(timeout=timeout, transport=_Metered(**kwargs),
                        headers={**_auth_headers(provider), SOURCE_HEADER: source})


def async_http_client(source: str, *, provider: str = "openrouter", timeout: float = 60,
                      limits: httpx.Limits | None = None) -> httpx.AsyncClient:
    """The async twin of http_client()."""
    _check(source)
    kwargs = {"limits": limits} if limits else {}
    return httpx.AsyncClient(timeout=timeout, transport=_AsyncMetered(**kwargs),
                             headers={**_auth_headers(provider), SOURCE_HEADER: source})


# ---------------------------------------------------------------------------
# SDK calls: chat, structured output, transcription
# ---------------------------------------------------------------------------

_sdk: dict[str, OpenAI] = {}
_sdk_lock = threading.Lock()


def _openai(provider: str) -> OpenAI:
    with _sdk_lock:
        if provider not in _sdk:
            base_url = OPENROUTER_BASE_URL if provider == "openrouter" else DEEPINFRA_BASE_URL
            key = _auth_headers(provider)["Authorization"].removeprefix("Bearer ")
            _sdk[provider] = OpenAI(
                base_url=base_url, api_key=key, timeout=LLM_TIMEOUT_SECONDS,
                http_client=httpx.Client(transport=_Metered(), timeout=LLM_TIMEOUT_SECONDS))
        return _sdk[provider]


def chat(source: str, **kwargs: Any) -> Any:
    """client.chat.completions.create(**kwargs) on OpenRouter, attributed to
    `source`. Asks OpenRouter to return the call's cost."""
    _check(source)
    extra_headers = {**(kwargs.pop("extra_headers", None) or {}), SOURCE_HEADER: source}
    extra_body = {"usage": {"include": True},
                  **(kwargs.pop("extra_body", None) or {})}
    return _openai("openrouter").chat.completions.create(
        extra_headers=extra_headers, extra_body=extra_body, **kwargs)


def transcribe(source: str, **kwargs: Any) -> Any:
    """client.audio.transcriptions.create(**kwargs) on DeepInfra."""
    _check(source)
    headers = {SOURCE_HEADER: source}
    if kwargs.get("model"):
        headers[MODEL_HEADER] = str(kwargs["model"])
    return _openai("deepinfra").audio.transcriptions.create(extra_headers=headers, **kwargs)


def check_transcription_configured() -> None:
    """Raise unless DeepInfra is configured; makes no request."""
    _auth_headers("deepinfra")


class ModelRefusal(RuntimeError):
    """The model declined to answer. Re-asking the same thing will not help."""


# Retrying these is pure latency: a bad key, a blocked account, a refusal and
# an unregistered source all fail identically on the next attempt. Only
# malformed, empty or schema-violating output is worth a second try with a
# different response_format.
NON_RETRYABLE = (AuthenticationError, PermissionDeniedError, ModelRefusal, UnknownSource)

T = TypeVar("T", bound=BaseModel)


def parse_structured[T: BaseModel](
    source: str,
    *,
    model: str,
    messages: list[dict[str, Any]],
    schema_model: type[T],
    reasoning: dict[str, Any] | None = None,
    **kwargs: Any,
) -> T:
    """Return a validated Pydantic object, replacing beta.chat.completions.parse.

    The SDK's .parse() helper is OpenAI-specific and assumes strict
    json_schema support. Across OpenRouter that assumption does not hold for
    every model and provider, so this tries the strict path first and falls
    back to plain JSON mode, validating with Pydantic either way. Validation
    is what actually guarantees the shape -- the response_format is an
    optimisation, not the contract. Every attempt is billed, and recorded,
    under `source`.
    """
    _check(source)
    schema = schema_model.model_json_schema()
    schema["additionalProperties"] = False

    strict_format = {
        "type": "json_schema",
        "json_schema": {"name": schema_model.__name__, "strict": True, "schema": schema},
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
        # Logged with every failure: 'length' means the reply was cut off at
        # max_tokens, which reads as a JSON syntax error, not as truncation.
        finish_reason = reasoning_tokens = None
        try:
            extra = dict(kwargs)
            if reasoning_cfg is not None:
                extra["extra_body"] = {**extra.get("extra_body", {}), "reasoning": reasoning_cfg}
            resp = chat(source, model=model, messages=messages,
                        response_format=response_format, **extra)
            choice = resp.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            details = getattr(getattr(resp, "usage", None), "completion_tokens_details", None)
            reasoning_tokens = getattr(details, "reasoning_tokens", None)
            msg = choice.message
            if getattr(msg, "refusal", None):
                raise ModelRefusal(f"Model refused: {msg.refusal}")

            content = (msg.content or "").strip()
            if not content:
                raise ValueError(f"Empty response body (finish_reason={choice.finish_reason})")
            # Some models wrap JSON in prose or a fenced block.
            start, end = content.find("{"), content.rfind("}")
            if start != -1 and end > start:
                content = content[start : end + 1]
            return schema_model.model_validate(json.loads(content))

        except NON_RETRYABLE:
            raise
        except Exception as exc:
            last_error = exc
            if i + 1 < len(attempts):
                log.warning(
                    "structured output via %s failed (%s, finish_reason=%s, "
                    "reasoning_tokens=%s); retrying with %s",
                    response_format["type"], exc, finish_reason, reasoning_tokens,
                    attempts[i + 1][0]["type"])

    raise RuntimeError(f"Structured output failed for {model}: {last_error}")


@contextlib.contextmanager
def recording() -> Iterator[list[Call]]:
    """Collect the calls made inside the block (tests, or a script that
    reports its own spend)."""
    calls: list[Call] = []
    ledger.listeners.append(calls.append)
    try:
        yield calls
    finally:
        ledger.listeners.remove(calls.append)


__all__ = [
    "AI_HOSTS",
    "CHAT_URL",
    "CREDITS_URL",
    "DEEPINFRA_BASE_URL",
    "ELEVENLABS_TTS_URL",
    "JEV_URL",
    "NON_RETRYABLE",
    "OPENROUTER_BASE_URL",
    "SOURCES",
    "Call",
    "MissingSource",
    "ModelRefusal",
    "UnknownSource",
    "async_http_client",
    "chat",
    "check_transcription_configured",
    "elevenlabs_configured",
    "http_client",
    "ledger",
    "parse_structured",
    "recording",
    "transcribe",
]
