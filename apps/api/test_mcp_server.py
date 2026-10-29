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
from test_practice import USER, FakeStore

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def test_record_practice_over_http_as_the_signed_in_user(monkeypatch):
    # Wired the way app.py wires it: the MCP route joins the app, and a
    # middleware in front sets request.state.user (auth.AuthMiddleware in prod).
    store = FakeStore()
    monkeypatch.setattr(mcp_server, "get_practice_store", lambda: store)

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
        [tool] = tools["result"]["tools"]
        assert tool["name"] == "record_practice"
        assert tool["annotations"]["readOnlyHint"] is False

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
