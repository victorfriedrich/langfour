"""Onboarding preview and daily words (onboarding.py)."""

import os

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("REQUIRE_SERVICE_ROLE", "0")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("DEEPINFRA_API_KEY", "test-key")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.test-signature",
)

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import auth
import home
import onboarding
from test_home import KNOWN_WORD, USER, build, video


class Store(onboarding.OnboardingStore):
    """Level words and validity without Supabase. Word 2 is not a valid
    dictionary word (a name, say), so it must never be suggested."""

    def __init__(self, invalid=(2,)):
        self.invalid = set(invalid)
        self.level_reads = 0

    def level_words(self, language, level):
        self.level_reads += 1
        return {KNOWN_WORD}

    def valid(self, word_ids):
        return {w for w in word_ids if w not in self.invalid}


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    # The small test videos have under 100 distinct words.
    monkeypatch.setattr(home, "MIN_DISTINCT_WORDS", 1)
    monkeypatch.setattr(onboarding, "MIN_DISTINCT_WORDS", 1)
    onboarding._previews.clear()
    yield
    onboarding._previews.clear()


def corpus():
    # `known` of every 100 words are the learner's one known word; the rest are
    # new, words 2.. one each, so the fewer known, the more new words a video has.
    return build([
        video("cook9500000", 95, category="Cooking", creator="Ana"),
        video("cook8900000", 89, category="Cooking", creator="Ana"),
        video("cook8000000", 80, category="Cooking", creator="Bea"),
        video("trip9100000", 91, category="Travel", creator="Cai"),
        video("trip7000000", 70, category="Travel", creator="Cai"),
    ])


def test_preview_shows_the_level_videos_in_the_chosen_topics():
    p = onboarding.preview(Store(), corpus(), "es", "A1", ["Cooking"])
    assert p.words == 1
    assert [v.id for v in p.videos] == ["cook9500000", "cook8900000", "cook8000000"]
    assert p.videos[0].understood == 95.0
    assert set(p.topics) == {"Cooking", "Travel"}


def test_preview_counts_what_two_weeks_of_daily_words_open_up():
    p = onboarding.preview(Store(), corpus(), "es", "A1", ["Cooking"])
    assert p.now == 1                       # only the 95% video
    # New words 2..21 are in every Cooking video below 95%; learning them
    # lifts the 89% and 80% videos past 90% well within two weeks.
    assert p.pace[10] >= p.now
    assert p.pace[10] <= p.pace[15] <= p.pace[25] <= 3
    assert p.pace[25] == 3


def test_preview_without_topics_covers_every_video():
    p = onboarding.preview(Store(), corpus(), "es", "A1", [])
    assert len(p.videos) == 5
    assert p.now == 2                       # 95% Cooking and 91% Travel


def test_preview_is_kept_per_level_and_topics():
    store, rec = Store(), corpus()
    onboarding.preview(store, rec, "es", "A1", ["Cooking"])
    onboarding.preview(store, rec, "es", "A1", ["Cooking"])
    assert store.level_reads == 1
    onboarding.preview(store, rec, "es", "A1", ["Travel"])
    assert store.level_reads == 2


def test_daily_words_skip_known_saved_and_invalid_words():
    out = onboarding.daily_words(Store(invalid={2}), corpus(), "es", {KNOWN_WORD}, {3, 4},
                                 ["Cooking"], 5)
    assert out.word_ids == [5, 6, 7, 8, 9]


def test_daily_words_take_each_topic_in_turn():
    rec = build([
        video("cook0000000", 90, category="Cooking", words=(102, 103)),
        video("cook0000001", 90, category="Cooking", words=(102, 103)),
        video("trip0000000", 90, category="Travel", words=(110, 111)),
        video("trip0000001", 90, category="Travel", words=(110, 111)),
    ])
    out = onboarding.daily_words(Store(invalid=set(range(2, 102))), rec, "es", {KNOWN_WORD},
                                 set(), ["Cooking", "Travel"], 4)
    assert out.word_ids[:2] == [102, 110]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    from app import app
    monkeypatch.setattr(auth, "verify_token", lambda t: SimpleNamespace(id=USER, is_anonymous=True))
    store = Store()
    app.dependency_overrides[onboarding.get_onboarding_store] = lambda: store
    rec = corpus()

    async def no_words(user_id):
        return []
    rec.get_known_words = no_words
    rec.get_saved_words = no_words
    app.state.recommender = rec
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_preview_needs_no_account(client):
    response = client.get("/api/onboarding/preview?language=es&level=A1&topics=Cooking")
    assert response.status_code == 200
    assert response.json()["videos"][0]["id"] == "cook9500000"


def test_preview_rejects_an_unknown_level(client):
    assert client.get("/api/onboarding/preview?language=es&level=C2").status_code == 422


def test_daily_words_need_an_account(client):
    assert client.get("/api/daily-words?language=es").status_code in (401, 403)
    response = client.get("/api/daily-words?language=es&n=3&topics=Travel",
                          headers={"authorization": "Bearer demo-session"})
    assert response.status_code == 200
    assert len(response.json()["word_ids"]) == 3
