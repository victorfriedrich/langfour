import os

# supabase_client builds its client at import time; nothing here touches the network.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("REQUIRE_SERVICE_ROLE", "0")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.test-signature",
)

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import mcp_server
import test_grammar
import test_vocabulary
from test_practice import USER, FakeStore

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def test_record_practice_over_http_as_the_signed_in_user(monkeypatch):
    # Wired the way app.py wires it: the MCP route joins the app, and a
    # middleware in front sets request.state.user (auth.AuthMiddleware in prod).
    store = FakeStore()
    vocab_store = test_vocabulary.FakeStore()
    monkeypatch.setattr(mcp_server, "get_practice_store", lambda: store)
    monkeypatch.setattr(mcp_server, "get_vocabulary_store", lambda: vocab_store)
    grammar_store = test_grammar.FakeStore()
    monkeypatch.setattr(mcp_server, "get_grammar_store", lambda: grammar_store)

    @asynccontextmanager
    async def lifespan(_):
        async with mcp_server.mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def signed_in(request: Request, call_next):
        request.state.user = SimpleNamespace(id=USER)
        return await call_next(request)

    app.router.routes.extend(mcp_server.mcp.streamable_http_app().routes)

    with TestClient(app) as client:
        tools = client.post("/mcp", headers=HEADERS,
                            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()
        read_only = {t["name"]: t["annotations"]["readOnlyHint"] for t in tools["result"]["tools"]}
        assert read_only == {"record_practice": False, "record_exposure": False,
                             "set_word_status": False, "record_grammar": False,
                             "add_words": False,
                             "get_vocabulary": True, "score_text": True,
                             "get_grammar_overview": True, "get_grammar_details": True}

        marked = client.post("/mcp", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "set_word_status",
                       "arguments": {"language": "es", "words": ["de"], "status": "known"}},
        }).json()["result"]
        assert not marked.get("isError"), marked
        assert ("set_status", USER, [7, 8], "known") in vocab_store.calls
        vocab_store.calls.clear()

        added = client.post("/mcp", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "add_words",
                       "arguments": {"language": "es", "words": ["comer"], "status": "learning"}},
        }).json()["result"]
        assert not added.get("isError"), added
        assert vocab_store.calls == [("add_words", USER, [3], "learning")]
        vocab_store.calls.clear()

        vocab = client.post("/mcp", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "get_vocabulary", "arguments": {}},
        }).json()["result"]
        assert not vocab.get("isError"), vocab
        assert vocab_store.calls == [("vocabulary", USER, None, "due", 50),
                                     ("recall_events", USER, "es")]

        overview = client.post("/mcp", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "get_grammar_overview", "arguments": {}},
        }).json()["result"]
        assert not overview.get("isError"), overview
        body = overview.get("structuredContent") or json.loads(overview["content"][0]["text"])
        assert body["language"] == "es" and "· es.ser  Ser" in body["overview"]

        recorded = client.post("/mcp", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "record_grammar", "arguments": {
                "language": "es",
                "results": [{"concept": "es.ser.origin", "kind": "produced", "correct": True,
                             "sentence": "Soy de Bonn."}],
            }},
        }).json()["result"]
        assert not recorded.get("isError"), recorded
        assert grammar_store.recorded[0] == USER

        too_many = client.post("/mcp", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "get_grammar_details",
                       "arguments": {"chapters": ["es.ser", "es.estar_hay", "es.ser_estar_1",
                                                  "es.ser_estar_2", "es.ser_estar_3",
                                                  "es.condicional"]}},
        }).json()["result"]
        assert too_many.get("isError")

        too_long = client.post("/mcp", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "score_text",
                       "arguments": {"language": "es", "text": "a" * 20_001}},
        }).json()["result"]
        assert too_long.get("isError")

        res = client.post("/mcp", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "record_practice", "arguments": {
                "language": "es",
                "answers": [{"word": "hablar", "direction": "produce", "correct": False}],
            }},
        }).json()

    result = res["result"]
    assert not result.get("isError"), result
    summary = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert (summary["recorded"], summary["queued"]) == (1, 1)
    assert store.events[0]["user_id"] == USER
    assert [r["outcome"] for r in store.outbox.values()] == ["again"]
