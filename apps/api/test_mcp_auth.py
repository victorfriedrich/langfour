"""Exercise discovery and bearer isolation through the actual MCP HTTP route."""
import os

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("REQUIRE_SERVICE_ROLE", "0")
os.environ.setdefault("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.signature")

import base64
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
import mcp_auth
import mcp_server
from test_practice import USER, FakeStore


def token(**changes):
    claims = {
        "iss": mcp_auth.MCP_ISSUER,
        "aud": ["authenticated", mcp_auth.MCP_RESOURCE_URL],
        "sub": USER, "client_id": "client-a", "role": "langfour_mcp",
        "is_anonymous": False, "exp": time.time() + 3600,
    } | changes
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{body}.test-signature"


@pytest.fixture
def client(monkeypatch):
    # MCP managers run once; each test owns a fresh transport lifetime.
    monkeypatch.setattr(mcp_server.mcp, "_session_manager", None)
    # Only the remote signature/session verifier is mocked. Claims checks,
    # middleware, OAuth discovery, and MCP routing run as deployed.
    monkeypatch.setattr(auth, "verify_token", lambda t: SimpleNamespace(id=USER, is_anonymous=False))
    @asynccontextmanager
    async def lifespan(_):
        async with mcp_server.mcp.session_manager.run():
            yield
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(auth.AuthMiddleware)
    app.include_router(mcp_auth.router)
    app.router.routes.extend(mcp_server.mcp.streamable_http_app().routes)
    @app.get("/api/private")
    def private():
        return {"ok": True}
    with TestClient(app) as client:
        yield client


def test_discovery_and_challenge_do_not_trust_host(client):
    for path in mcp_auth.MCP_PUBLIC_PATHS:
        response = client.get(path, headers={"host": "attacker.example"})
        assert response.status_code == 200
        assert response.json()["resource"] == mcp_auth.MCP_RESOURCE_URL
        assert response.json()["authorization_servers"] == [mcp_auth.MCP_ISSUER]
    response = client.post("/mcp")
    assert response.status_code == 401
    assert mcp_auth.MCP_METADATA_URL in response.headers["www-authenticate"]
    assert client.get("/.well-known/not-public").status_code == 401


def test_oauth_access_reaches_tool_as_owner(client, monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(mcp_server, "get_practice_store", lambda: store)
    response = client.post("/mcp", headers={
        "authorization": f"Bearer {token()}", "accept": "application/json, text/event-stream",
    }, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "record_practice", "arguments": {
            "language": "es", "answers": [{"word": "hablar", "direction": "produce", "correct": False}],
        },
    }})
    assert response.status_code == 200
    assert not response.json()["result"].get("isError")
    assert store.events[0]["user_id"] == USER


@pytest.mark.parametrize("changes", [
    {"aud": "authenticated"}, {"aud": ["authenticated", "https://other.example/mcp"]},
    {"iss": "https://other.supabase.co/auth/v1"}, {"exp": time.time() - 1},
    {"exp": None}, {"exp": True}, {"exp": float("nan")}, {"exp": float("inf")},
    {"client_id": ""}, {"role": "authenticated"}, {"sub": "other-user"},
    {"is_anonymous": True}, {"is_anonymous": None},
])
def test_invalid_claims_fail_even_after_upstream_verification(client, changes):
    response = client.post("/mcp", headers={"authorization": f"Bearer {token(**changes)}"})
    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["www-authenticate"]


def test_signature_failure_is_not_replaced_by_claims_check(client, monkeypatch):
    monkeypatch.setattr(auth, "verify_token", lambda t: None)
    assert client.post("/mcp", headers={"authorization": f"Bearer {token()}"}).status_code == 401


@pytest.mark.parametrize("path", ["/api/private", "/integrations/remnote", "/sync/remnote/push"])
def test_oauth_token_cannot_reach_web_or_sync_api(client, path):
    assert client.get(path, headers={"authorization": f"Bearer {token()}"}).status_code == 401


def test_web_session_still_reaches_web_api(client):
    assert client.get("/api/private", headers={"authorization": "Bearer ordinary-session"}).status_code == 200


@pytest.mark.parametrize("raw", ["garbage", "a.%%%.c", "a.bnVsbA.c", "a.W10.c", "lf_rn_abc"])
def test_non_oauth_bearers_cannot_reach_mcp(client, raw):
    assert client.post("/mcp", headers={"authorization": f"Bearer {raw}"}).status_code == 401


def test_expiry_is_rechecked_even_when_signature_result_is_cached(client, monkeypatch):
    user = SimpleNamespace(id=USER, is_anonymous=False)
    access_token = token(exp=time.time() + 60)
    monkeypatch.setattr(auth, "verify_token", lambda t: auth._cache_get(t))
    monkeypatch.setattr(auth, "_token_cache", {})
    auth._cache_put(access_token, user)
    assert auth._authenticate(access_token, "/mcp") == (user, None)
    now = time.time()
    monkeypatch.setattr(mcp_auth.time, "time", lambda: now + 61)
    assert auth._cache_get(access_token) is user
    assert client.post("/mcp", headers={"authorization": f"Bearer {access_token}"}).status_code == 401


def test_upstream_anonymous_user_cannot_authorize_mcp(client, monkeypatch):
    monkeypatch.setattr(auth, "verify_token", lambda t: SimpleNamespace(id=USER, is_anonymous=True))
    assert client.post("/mcp", headers={"authorization": f"Bearer {token()}"}).status_code == 401
