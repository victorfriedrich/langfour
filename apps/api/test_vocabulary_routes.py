"""/api/vocabulary/stuck and /api/vocabulary/status: signed-in only, common
words from the recommender's ranking, moves through the vocabulary store."""
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
from test_vocabulary import USER, StuckStore, seen
from vocabulary import STUCK_TOP, get_vocabulary_store

AUTH = {"authorization": "Bearer ordinary-session"}


class FakeRecommender:
    def __init__(self):
        self.asked = []

    def recommend_words_to_learn(self, language, known_word_ids, n_words=100):
        self.asked.append((language, known_word_ids, n_words))
        if language != "es":
            raise ValueError(language)
        return [{"word_id": w, "improvement": 0.9, "frequency": 100} for w in (23, 21, 24)]


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(auth, "verify_token", lambda t: SimpleNamespace(id=USER, is_anonymous=False))
    fake = StuckStore(events=[seen(23, "youtube:a")])
    app.dependency_overrides[get_vocabulary_store] = lambda: fake
    app.state.recommender = FakeRecommender()
    yield fake
    app.dependency_overrides.clear()


client = TestClient(app)


def test_lists_stuck_words_in_corpus_order(store):
    response = client.get("/api/vocabulary/stuck?language=es", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"words": [
        {"word_id": 23, "word": "que", "translation": "that, which", "videos": 1, "lookups": 0},
        {"word_id": 24, "word": "quedar", "translation": "to stay", "videos": 0, "lookups": 0},
    ]}
    # Every common word, known ones included: "common" doesn't depend on the user.
    assert app.state.recommender.asked == [("es", [], STUCK_TOP)]


def test_moves_ticked_words_to_known(store):
    response = client.post("/api/vocabulary/status", json={"word_ids": [10, 11]}, headers=AUTH)
    assert response.json() == {"moved": [10]}
    assert ("set_status", USER, [10], "known") in store.calls


def test_refuses_unknown_languages_and_empty_moves(store):
    assert client.get("/api/vocabulary/stuck?language=xx", headers=AUTH).status_code == 422
    assert client.post("/api/vocabulary/status", json={"word_ids": []}, headers=AUTH).status_code == 422


def test_requires_a_session(store):
    assert client.get("/api/vocabulary/stuck?language=es").status_code == 401
    assert client.post("/api/vocabulary/status", json={"word_ids": [10]}).status_code == 401
