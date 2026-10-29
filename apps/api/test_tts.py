"""/api/tts: short texts only, signed-in only, each text paid for once."""
import base64
import os
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("REQUIRE_SERVICE_ROLE", "0")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("DEEPINFRA_API_KEY", "test-key")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.test-signature",
)

import pytest
from fastapi.testclient import TestClient

import auth
import tts
from app import app

AUTH = {"authorization": "Bearer ordinary-session"}


@pytest.fixture
def calls(monkeypatch):
    monkeypatch.setattr(auth, "verify_token", lambda t: SimpleNamespace(id="user-1", is_anonymous=False))
    monkeypatch.setattr(tts, "_cache", type(tts._cache)())
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    sent = []

    def fake_post(url, **kwargs):
        sent.append((url, kwargs))
        return SimpleNamespace(ok=True, status_code=200, content=b"mp3-bytes")

    monkeypatch.setattr(tts.requests, "post", fake_post)
    return sent


client = TestClient(app)


def test_speaks_a_word_once_and_then_from_cache(calls):
    for _ in range(2):
        response = client.post("/api/tts", json={"text": "  caía ", "language": "spanish"}, headers=AUTH)
        assert response.status_code == 200
        assert base64.b64decode(response.json()["audio"]) == b"mp3-bytes"
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url.endswith(f"/{tts.DEFAULT_VOICE_ID}")
    assert kwargs["json"]["text"] == "caía"
    assert kwargs["json"]["language_code"] == "es"
    assert kwargs["headers"]["xi-api-key"] == "el-test"


def test_refuses_long_text_and_unknown_language(calls):
    long_text = client.post("/api/tts", json={"text": "a" * 101, "language": "es"}, headers=AUTH)
    unknown = client.post("/api/tts", json={"text": "hola", "language": "xx"}, headers=AUTH)
    assert (long_text.status_code, unknown.status_code) == (400, 400)
    assert calls == []


def test_requires_a_session(calls):
    assert client.post("/api/tts", json={"text": "hola", "language": "es"}).status_code == 401


def test_unconfigured_key_is_503(calls, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    response = client.post("/api/tts", json={"text": "hola", "language": "es"}, headers=AUTH)
    assert response.status_code == 503
