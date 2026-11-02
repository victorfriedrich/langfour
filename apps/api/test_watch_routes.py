"""/api/watch: signed-in only, ids checked, history writes followed by the
heard words of what was just watched."""
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
from app import app
from test_watch import USER, A, B, FakeStore, at, videos  # noqa: F401 (fixture)
from watch import get_watch_store

AUTH = {"authorization": "Bearer ordinary-session"}
client = TestClient(app)


@pytest.fixture
def store(monkeypatch, videos):  # noqa: F811
    monkeypatch.setattr(auth, "verify_token", lambda t: SimpleNamespace(id=USER, is_anonymous=False))
    fake = FakeStore(statuses={2: "learning"})
    app.dependency_overrides[get_watch_store] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def test_desktop_watch_marks_and_logs_the_learning_words_heard(store):
    response = client.post("/api/watch", json={"video_id": A, "language": "es", "share": 0.71},
                           headers=AUTH)
    assert response.json() == {"indexed": True, "watched": True}
    assert client.get(f"/api/watch/{A}?language=es", headers=AUTH).json()["watched"]
    assert [(e["word_id"], e["kind"]) for e in store.vocab.events] == [(2, "exposure")]

    client.post("/api/watch/unmark", json={"video_id": A}, headers=AUTH)
    assert client.get(f"/api/watch/{A}?language=es", headers=AUTH).json() == \
        {"indexed": True, "watched": False}


def test_history_read_keeps_indexed_ids_only(store):
    response = client.post("/api/watch/history", headers=AUTH, json={"language": "es", "items": [
        {"video_id": A, "share": 0.9, "day": 1},
        {"video_id": "dQw4w9WgXcQ", "share": 1.0, "day": 0},
    ]})
    assert response.json() == {"kept": 1}
    assert set(store.data) == {A}
    assert client.post("/api/watch/history/off", headers=AUTH).status_code == 204
    assert store.data == {}


def test_recap_needs_one_day_with_a_time_zone(store):
    store.data[A] = {"video_id": A, "language": "es", "share": 1.0, "source": "desktop",
                     "watched_at": at(1), "unmarked_at": None, "created_at": at(1)}
    store.data[B] = {**store.data[A], "video_id": B}
    query = "language=es&day=2026-11-01&start=2026-10-31T23:00:00%2B00:00&end=2026-11-01T23:00:00%2B00:00"
    response = client.get(f"/api/watch/recap?{query}", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["videos"] == 2
    week = "language=es&day=2026-11-01&start=2026-10-25T23:00:00%2B00:00&end=2026-11-01T23:00:00%2B00:00"
    assert client.get(f"/api/watch/recap?{week}", headers=AUTH).status_code == 422
    naive = "language=es&day=2026-11-01&start=2026-10-31T23:00:00&end=2026-11-01T23:00:00"
    assert client.get(f"/api/watch/recap?{naive}", headers=AUTH).status_code == 422

    assert client.post("/api/watch/recap/close", json={"day": "2026-11-01"}, headers=AUTH).status_code == 204
    assert client.get(f"/api/watch/recap?{query}", headers=AUTH).json()["words"] == []


def test_refuses_bad_ids_and_requires_a_session(store):
    assert client.get("/api/watch/../etc?language=es", headers=AUTH).status_code in (404, 422)
    assert client.get("/api/watch/short?language=es", headers=AUTH).status_code == 422
    assert client.post("/api/watch", json={"video_id": A, "language": "es", "share": 0.4},
                       headers=AUTH).status_code == 422
    assert client.get(f"/api/watch/{A}?language=es").status_code == 401
    assert client.post("/api/watch/history", json={"language": "es", "items": []}).status_code == 401
