"""/api/channels/...: signed-in only, UC ids only, favourite queues the
channel's uploads in the background."""
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
import channels
from app import app
from test_channels import CHANNEL, CHANNEL_DONE, USER, Store, recommender

AUTH = {"authorization": "Bearer ordinary-session"}
client = TestClient(app)


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(auth, "verify_token", lambda t: SimpleNamespace(id=USER, is_anonymous=False))
    monkeypatch.setattr(channels, "MIN_DISTINCT_WORDS", 1)
    fake = Store(CHANNEL_DONE)
    app.dependency_overrides[channels.get_channel_store] = lambda: fake
    app.state.recommender = recommender()
    yield fake
    app.dependency_overrides.clear()


def test_shows_a_channels_tab(store):
    response = client.get(f"/api/channels/{CHANNEL}?language=es", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["favourite"] is False and body["videos"] == 6 and body["progress"] is None
    assert [w["word"] for w in body["core_words"]["words"]] == ["el cofre", "el mago"]


def test_favourite_queues_the_uploads_after_answering(store, monkeypatch):
    queued = []
    monkeypatch.setenv("YOUTUBE_API_KEY", "key")
    monkeypatch.setattr(channels, "queue_channel", lambda *a: queued.append(a))
    response = client.post(f"/api/channels/{CHANNEL}/favourite",
                           json={"language": "es", "favourite": True}, headers=AUTH)
    assert response.json() == {"favourite": True}
    assert queued == [(store, USER, CHANNEL, "es", "key")]

    # Already a favourite and its listing finished: no second one.
    store.set_uploads_outcome(USER, CHANNEL, "queued")
    response = client.post(f"/api/channels/{CHANNEL}/favourite",
                           json={"language": "es", "favourite": True}, headers=AUTH)
    assert response.json() == {"favourite": True} and len(queued) == 1

    response = client.post(f"/api/channels/{CHANNEL}/favourite",
                           json={"language": "es", "favourite": False}, headers=AUTH)
    assert response.json() == {"favourite": False} and len(queued) == 1


def test_reads_the_favourite_alone(store):
    assert client.get(f"/api/channels/{CHANNEL}/favourite", headers=AUTH).json() == {"favourite": False}
    store.favourite(USER, CHANNEL, "es")
    assert client.get(f"/api/channels/{CHANNEL}/favourite", headers=AUTH).json() == {"favourite": True}
    assert client.get(f"/api/channels/{CHANNEL}/favourite").status_code == 401


def test_a_visit_retries_a_listing_that_did_not_finish(store, monkeypatch):
    queued = []
    monkeypatch.setenv("YOUTUBE_API_KEY", "key")
    monkeypatch.setattr(channels, "queue_channel", lambda *a: queued.append(a))
    assert client.get(f"/api/channels/{CHANNEL}/favourite", headers=AUTH).status_code == 200
    assert queued == []  # not a favourite

    store.favourite(USER, CHANNEL, "de")
    client.get(f"/api/channels/{CHANNEL}/favourite", headers=AUTH)
    assert queued == [(store, USER, CHANNEL, "de", "key")]

    store.set_uploads_outcome(USER, CHANNEL, "other_language")
    client.get(f"/api/channels/{CHANNEL}/favourite", headers=AUTH)
    assert len(queued) == 1


def test_refuses_handles_unknown_languages_and_missing_sessions(store):
    assert client.get("/api/channels/@viajes?language=es", headers=AUTH).status_code == 422
    assert client.get(f"/api/channels/{CHANNEL}?language=xx", headers=AUTH).status_code == 422
    app.state.recommender.languages = ["fr"]
    assert client.get(f"/api/channels/{CHANNEL}?language=es", headers=AUTH).status_code == 404
    assert client.get(f"/api/channels/{CHANNEL}?language=es").status_code == 401
    assert client.post(f"/api/channels/{CHANNEL}/core-words", json={"language": "es"}).status_code == 401
