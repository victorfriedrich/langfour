"""/api/videos/fit and /api/videos/queue: signed-in only, ids checked before
they reach the recommender or the queue, and videos YouTube says are in
another language neither offered nor queued."""
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
import video_fit_routes
from app import app
from conftest import FakeSupabase
from conftest import queued as pending

AUTH = {"authorization": "Bearer ordinary-session"}
USER = "11111111-1111-1111-1111-111111111111"
A, B, C, D = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"


class FakeRecommender:
    languages = ["es"]

    def __init__(self):
        self.asked = []

    def known_word_ids(self, user_id):
        self.asked.append(("known", user_id))
        return [7]

    def fit_videos(self, video_ids, word_ids, language):
        self.asked.append(("fit", video_ids, word_ids, language))
        fits = {A: {"status": "scored", "percentUnderstood": 97.1, "newWords": 12},
                B: {"status": "hidden"}}
        return {v: fits.get(v, {"status": "unindexed"}) for v in video_ids}


class FakeYouTube:
    """channels.stated_languages: every id unstated unless set in `languages`."""

    def __init__(self):
        self.languages = {}
        self.asked = []
        self.down = False

    def __call__(self, video_ids, key):
        assert key == "key"
        self.asked.append(video_ids)
        if self.down:
            raise RuntimeError("quotaExceeded")
        return {v: self.languages.get(v, "") for v in video_ids}


@pytest.fixture
def youtube(monkeypatch):
    fake = FakeYouTube()
    monkeypatch.setenv("YOUTUBE_API_KEY", "key")
    monkeypatch.setattr(channels, "stated_languages", fake)
    monkeypatch.setattr(video_fit_routes, "_stated", {})
    return fake


@pytest.fixture
def recommender(monkeypatch, youtube):
    monkeypatch.setattr(auth, "verify_token", lambda t: SimpleNamespace(id=USER, is_anonymous=False))
    app.state.recommender = FakeRecommender()
    return app.state.recommender


client = TestClient(app)


def test_fit_scores_each_id_once_with_the_users_known_words(recommender):
    response = client.post("/api/videos/fit", headers=AUTH,
                           json={"language": "es", "video_ids": [A, B, C, A]})
    assert response.status_code == 200
    assert response.json() == {"videos": {
        A: {"status": "scored", "percentUnderstood": 97.1, "newWords": 12},
        B: {"status": "hidden"},
        C: {"status": "unindexed"},
    }}
    assert recommender.asked == [("known", USER), ("fit", [A, B, C], [7], "es")]


def test_fit_refuses_bad_ids_too_many_ids_and_unknown_languages(recommender):
    def fit(language, ids):
        return client.post("/api/videos/fit", headers=AUTH,
                           json={"language": language, "video_ids": ids}).status_code

    assert fit("es", ["not an id"]) == 422
    assert fit("es", []) == 422
    assert fit("es", [A] * (video_fit_routes.MAX_FIT_IDS + 1)) == 422
    assert fit("xx", [A]) == 422
    assert fit("de", [A]) == 404  # a language without a corpus here
    assert recommender.asked == []


def test_queue_adds_the_video_at_the_user_tier(recommender, monkeypatch):
    sb = FakeSupabase([pending(B, status="done")])
    monkeypatch.setattr(video_fit_routes, "supabase", sb)

    response = client.post("/api/videos/queue", headers=AUTH, json={"language": "es", "video_id": A})
    assert response.json() == {"status": "pending"}
    assert sb.row(A)["priority"] == 10 and sb.row(A)["submitted_by"] == USER
    response = client.post("/api/videos/queue", headers=AUTH, json={"language": "es", "video_id": B})
    assert response.json() == {"status": "done"}
    assert client.post("/api/videos/queue", headers=AUTH,
                       json={"language": "es", "video_id": "x"}).status_code == 422


def test_queue_stops_at_the_users_waiting_limit(recommender, monkeypatch):
    sb = FakeSupabase([pending(B, submitted_by=USER)])
    monkeypatch.setattr(video_fit_routes, "supabase", sb)
    monkeypatch.setattr(channels, "MAX_WAITING", 1)

    response = client.post("/api/videos/queue", headers=AUTH, json={"language": "es", "video_id": A})
    assert response.status_code == 429
    assert [r["video_id"] for r in sb.rows] == [B]


def test_fit_asks_youtube_the_language_of_unindexed_videos_only(recommender, youtube):
    youtube.languages = {C: "en", D: "es"}
    response = client.post("/api/videos/fit", headers=AUTH,
                           json={"language": "es", "video_ids": [A, B, C, D]})
    assert response.json()["videos"] == {
        A: {"status": "scored", "percentUnderstood": 97.1, "newWords": 12},
        B: {"status": "hidden"},
        C: {"status": "other_language", "language": "en"},
        D: {"status": "unindexed"},
    }
    assert youtube.asked == [[C, D]]

    # Asked once per video: scrolling back costs no quota.
    client.post("/api/videos/fit", headers=AUTH, json={"language": "es", "video_ids": [C, D]})
    assert youtube.asked == [[C, D]]


def test_fit_offers_add_as_before_when_youtube_cannot_say(recommender, youtube, monkeypatch):
    youtube.down = True
    body = {"language": "es", "video_ids": [C]}
    assert client.post("/api/videos/fit", headers=AUTH, json=body).json()["videos"] == {
        C: {"status": "unindexed"}}
    # A failure isn't remembered: the next scroll asks again.
    youtube.down = False
    youtube.languages = {C: "en"}
    assert client.post("/api/videos/fit", headers=AUTH, json=body).json()["videos"] == {
        C: {"status": "other_language", "language": "en"}}

    monkeypatch.delenv("YOUTUBE_API_KEY")
    video_fit_routes._stated.clear()
    assert client.post("/api/videos/fit", headers=AUTH, json=body).json()["videos"] == {
        C: {"status": "unindexed"}}
    assert len(youtube.asked) == 2


def test_queue_refuses_a_video_in_another_language(recommender, youtube, monkeypatch):
    sb = FakeSupabase([])
    monkeypatch.setattr(video_fit_routes, "supabase", sb)
    monkeypatch.setattr(channels, "MAX_WAITING", 0)  # the language answers first
    youtube.languages = {A: "en"}

    response = client.post("/api/videos/queue", headers=AUTH, json={"language": "es", "video_id": A})
    assert response.status_code == 200
    assert response.json() == {"status": "other_language", "language": "en"}
    assert sb.rows == []


def test_queue_queues_as_before_when_youtube_cannot_say(recommender, youtube, monkeypatch):
    sb = FakeSupabase([])
    monkeypatch.setattr(video_fit_routes, "supabase", sb)
    youtube.down = True
    response = client.post("/api/videos/queue", headers=AUTH, json={"language": "es", "video_id": A})
    assert response.json() == {"status": "pending"} and sb.row(A)["lang"] == "es"


def test_requires_a_session(recommender):
    assert client.post("/api/videos/fit", json={"language": "es", "video_ids": [A]}).status_code == 401
    assert client.post("/api/videos/queue", json={"language": "es", "video_id": A}).status_code == 401
