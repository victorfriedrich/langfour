"""One in-memory stand-in for the video_queue table, shared by every test.

There used to be two hand-written fakes, and the looser one hid a real bug: it
accepted `select(..., head=True)`, which the pinned postgrest (0.16.x, via
supabase==2.7.4) does not have, so `ingest.py status` passed its tests and
raised TypeError against the pinned dependency.

So this fake mirrors the PINNED client, not the newest one. Its method
signatures are deliberately narrow: a call the real builder would reject must
raise here too. The semantics that matter are

  * update() returns the rows it matched -- the compare-and-set claim reads it
  * upsert(ignore_duplicates=True) returns only rows actually inserted
  * a bulk payload's rows must share one key set (PostgREST nulls the rest)

It also holds the AI spend guard (see ai_gateway.py): every test fails if it
makes an AI request that did not come through the gateway, and gateway calls
only ever reach the `ai_upstream` fake, never a paid API.
"""

import json
import os
import socket

# Before anything imports ai_gateway: it refuses to load without a key, and
# tests must neither flush spend to Supabase nor start the flush thread.
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("DEEPINFRA_API_KEY", "test-key")
os.environ["AI_SPEND_SINK"] = "log"
os.environ["AI_SPEND_FLUSH_SECONDS"] = "0"

import httpx
import pytest
import requests.adapters

import ai_gateway


class BypassedGateway(AssertionError):
    """An AI request was made without ai_gateway, or a gateway call was not
    given a fake upstream."""


_real_sync = httpx.HTTPTransport.handle_request
_real_async = httpx.AsyncHTTPTransport.handle_async_request
_real_getaddrinfo = socket.getaddrinfo
_real_requests_send = requests.adapters.HTTPAdapter.send


@pytest.fixture(autouse=True)
def ai_spend_guard(monkeypatch):
    """Fail any test that reaches an AI host except through ai_gateway.

    The gateway's own transport is pointed at a fake that refuses (unless the
    test asks for `ai_upstream`), so a request that reaches the real network
    for an AI host can only have bypassed the gateway. The violation is kept
    as well as raised, because feature code often catches Exception."""
    violations: list[str] = []

    def bypass(where: str, host: str) -> BypassedGateway:
        msg = (f"AI request to {host} via {where} bypassed ai_gateway. Build the "
               "client with ai_gateway (chat, parse_structured, transcribe, "
               "http_client) and name a source.")
        violations.append(msg)
        return BypassedGateway(msg)

    def guarded_sync(self, request):
        if request.url.host in ai_gateway.AI_HOSTS:
            raise bypass("httpx", request.url.host)
        return _real_sync(self, request)

    async def guarded_async(self, request):
        if request.url.host in ai_gateway.AI_HOSTS:
            raise bypass("httpx (async)", request.url.host)
        return await _real_async(self, request)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if isinstance(host, bytes):
            host = host.decode()
        if host in ai_gateway.AI_HOSTS:
            raise bypass("a socket (requests, urllib, aiohttp ...)", host)
        return _real_getaddrinfo(host, *args, **kwargs)

    def guarded_requests_send(self, request, *args, **kwargs):
        # Checked here as well as at the socket: through a proxy, the socket
        # only ever sees the proxy's host.
        host = httpx.URL(request.url).host
        if host in ai_gateway.AI_HOSTS:
            raise bypass("requests", host)
        return _real_requests_send(self, request, *args, **kwargs)

    def unmocked(request: httpx.Request) -> httpx.Response:
        msg = (f"{request.method} {request.url} went through ai_gateway but the "
               "test has no fake for it: use the ai_upstream fixture.")
        violations.append(msg)
        raise BypassedGateway(msg)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded_sync)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded_async)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", guarded_requests_send)
    monkeypatch.setattr(ai_gateway, "_test_upstream", httpx.MockTransport(unmocked))
    yield violations
    ai_gateway.ledger.take()   # nothing a test spends carries over
    if violations:
        pytest.fail("\n".join(dict.fromkeys(violations)), pytrace=False)


class FakeUpstream:
    """Stands in for OpenRouter, DeepInfra and ElevenLabs behind the gateway.

    Answers every Jev question (uniform probabilities, noul 0.5), every chat
    completion with `chat_content`, every transcription with `transcript`, and
    every speech request with `audio`. Set `route` to answer differently."""

    COST = 0.0001

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.chat_content = "{}"
        self.transcript = "hola"
        self.audio = b"mp3-bytes"
        self.route = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.route is not None and (answer := self.route(request)) is not None:
            return answer
        path, usage = request.url.path, {"input_tokens": 10, "output_tokens": 2, "cost": self.COST}
        if path.endswith("/decisions"):
            sent = json.loads(request.content)
            return httpx.Response(200, json={
                "id": "gen-dec-test", "model": sent["model"], "usage": usage,
                "answers": {k: self.jev_answer(q) for k, q in sent["questions"].items()}})
        if path.endswith("/chat/completions"):
            sent = json.loads(request.content)
            return httpx.Response(200, json={
                "id": "gen-test", "object": "chat.completion", "created": 0, "model": sent["model"],
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": self.chat_content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12,
                          "cost": self.COST}})
        if path.endswith("/audio/transcriptions"):
            return httpx.Response(200, text=self.transcript, headers={"content-type": "text/plain"})
        if request.url.host == "api.elevenlabs.io":
            return httpx.Response(200, content=self.audio, headers={"content-type": "audio/mpeg"})
        return httpx.Response(404, json={"error": f"no fake for {request.url}"})

    @staticmethod
    def jev_answer(question: dict) -> dict:
        if question.get("type") == "noul":
            return {"type": "noul", "noul": 0.5}
        keys = list(question.get("criteria") or {"a": ""})
        return {"type": question.get("type", "choice"),
                "probabilities": {k: 1 / len(keys) for k in keys}}


@pytest.fixture
def ai_upstream(monkeypatch):
    """A fake for every AI provider, behind the gateway. Yields the fake;
    `fake.requests` holds what was sent."""
    fake = FakeUpstream()
    monkeypatch.setattr(ai_gateway, "_test_upstream", httpx.MockTransport(fake))
    return fake


class FakeQuery:
    # postgrest 0.16: select(self, *columns, count=None). No `head`.
    def __init__(self, rows):
        self.rows, self.filters, self.orders = rows, [], []
        self.op = self.payload = self.limit_n = self.span = None
        self.count_mode = None
        self.ignore_duplicates = False

    def select(self, *_, count=None):
        self.op, self.count_mode = "select", count
        return self

    def update(self, fields):
        self.op, self.payload = "update", fields
        return self

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        assert on_conflict == "video_id"
        if isinstance(rows, list):
            assert len({frozenset(r) for r in rows}) == 1, "bulk rows must share one key set"
        self.op, self.payload, self.ignore_duplicates = "upsert", rows, ignore_duplicates
        return self

    def delete(self):
        self.op = "delete"
        return self

    def range(self, start, end):
        self.span = (start, end)
        return self

    def eq(self, k, v):
        self.filters.append(lambda r: r.get(k) == v)
        return self

    def lt(self, k, v):
        self.filters.append(lambda r: r.get(k) is not None and r.get(k) < v)
        return self

    def gte(self, k, v):
        self.filters.append(lambda r: r.get(k) is not None and r.get(k) >= v)
        return self

    def order(self, k, desc=False):
        self.orders.append((k, desc))
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def execute(self):
        from types import SimpleNamespace
        match = [r for r in self.rows if all(f(r) for f in self.filters)]
        if self.op == "select":
            total = len(match)
            # Postgres sorts NULLs first under DESC; the claim query relies on
            # knowing that, so the fake must reproduce it rather than tidy it.
            for k, desc in reversed(self.orders):
                match.sort(key=lambda r: (r.get(k) is None, r.get(k) or 0), reverse=desc)
            match = match[:self.limit_n] if self.limit_n else match
            if self.span:
                match = match[self.span[0]:self.span[1] + 1]
            return SimpleNamespace(data=[dict(r) for r in match],
                                   count=total if self.count_mode else None)
        if self.op == "delete":
            self.rows[:] = [r for r in self.rows if r not in match]
            return SimpleNamespace(data=[dict(r) for r in match], count=None)
        if self.op == "update":
            for r in match:
                r.update(self.payload)
            return SimpleNamespace(data=[dict(r) for r in match], count=None)
        rows = self.payload if isinstance(self.payload, list) else [self.payload]
        written = []
        for row in rows:
            existing = next((r for r in self.rows if r["video_id"] == row["video_id"]), None)
            if existing is None:
                self.rows.append({"status": "pending", "attempts": 0, "priority": 0,
                                  "source": "discovery", **row})
                written.append(row)
            elif not self.ignore_duplicates:
                existing.update(row)
                written.append(row)
        return SimpleNamespace(data=written, count=None)


class FakeSupabase:
    def __init__(self, rows=()):
        self.rows = [dict(r) for r in rows]
        self.calls = []

    def table(self, name):
        self.calls.append(name)
        return FakeQuery(self.rows)

    def row(self, video_id):
        return next(r for r in self.rows if r["video_id"] == video_id)


def queued(video_id, **kw):
    """A pending row, with the columns the queue always has."""
    return {"video_id": video_id, "lang": "es", "status": "pending", "attempts": 0,
            "priority": 0, "score": 0.5, "source": "discovery", **kw}


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """Redirect the transcript corpus at a temp dir. processed_file() reads the
    module global at call time, so patching PROCESSED_DIR is enough."""
    import paths
    monkeypatch.setattr(paths, "PROCESSED_DIR", tmp_path)
    (tmp_path / "es").mkdir()
    return tmp_path / "es"
