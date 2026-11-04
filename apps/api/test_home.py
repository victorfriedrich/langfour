"""home.py: the web Videos page's grid, filters, empty state, channels at your
level, Not interested and the return from YouTube, against an in-memory store
and a real Recommender built from a small matrix."""

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

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.sparse import csr_matrix

import auth
import home
from home import HideRequest
from test_recommender import blank_recommender

USER = "11111111-1111-1111-1111-111111111111"
KNOWN_WORD, NEW_WORD = 0, 1
FOLLOWED = "UC" + "f" * 22


def video(vid, known, category="Travel", creator="", length=600, grammar=None, words=()):
    """`known` of every 100 words spoken are word 0, which the learner knows;
    the rest are words 2.. they don't, one each, so each video has its own
    new words. `words` are spoken too, once each: what the video is about."""
    return {"id": vid, "known": known, "category": category, "creator": creator,
            "length": length, "grammar": grammar, "words": words}


# What a video can be about, for Channels you might like: words past the
# 2..101 every video has, four per subject.
SUBJECTS = {subject: range(102 + 4 * i, 106 + 4 * i)
            for i, subject in enumerate(("ghosts", "trips", "food", "games"))}


def build(videos):
    width = 2 + 100 + 4 * len(SUBJECTS)
    rows = []
    for v in videos:
        row = np.zeros(width, dtype=np.int16)
        row[KNOWN_WORD] = v["known"]
        row[2:2 + 100 - v["known"]] = 1
        row[list(v["words"])] = 1
        rows.append(row)
    recommender = blank_recommender()
    recommender.filenames = {"es": [f"{v['id']}_processed.json" for v in videos]}
    recommender._index_matrix("es", csr_matrix(np.asarray(rows)))
    recommender.categories = {"es": [v["category"] for v in videos]}
    recommender.titles = {"es": [f"Title {v['id']}" for v in videos]}
    recommender.creators = {"es": [v["creator"] for v in videos]}
    recommender.lengths = {"es": [v["length"] for v in videos]}
    recommender.grammar = {"es": {v["id"]: v["grammar"] for v in videos if v["grammar"] is not None}}
    recommender.hidden_videos = set()
    return recommender


class Store(home.HomeStore):
    def __init__(self, watch=None, hides=(), favourites=(), followed=(), channel_ids=None,
                 saved=0):
        self.watch = watch or {}
        self.hidden = set(hides)
        self.favourite_ids = set(favourites)
        self.followed = set(followed)
        self.ids = channel_ids or {}
        self.saved = saved
        self.saved_args = None

    def known_words(self, user_id):
        return {KNOWN_WORD}

    def watch_rows(self, user_id):
        return self.watch

    def watch_row(self, user_id, video_id):
        return self.watch.get(video_id)

    def hides(self, user_id, language):
        return ({k for kind, k in self.hidden if kind == "video"},
                {k for kind, k in self.hidden if kind == "channel"})

    def hide(self, user_id, language, kind, key):
        self.hidden.add((kind, key))

    def unhide(self, user_id, language, kind, key):
        self.hidden.discard((kind, key))

    def favourites(self, user_id, language):
        return self.favourite_ids

    def videos_of(self, channel_ids, language):
        return self.followed if FOLLOWED in channel_ids else set()

    def channel_ids(self, video_ids):
        return {v: self.ids[v] for v in video_ids if v in self.ids}

    def saved_since(self, user_id, video_id, since):
        self.saved_args = (video_id, since)
        return self.saved


@pytest.fixture(autouse=True)
def short_videos_count(monkeypatch):
    monkeypatch.setattr(home, "MIN_DISTINCT_WORDS", 1)


def ids(page):
    return [v.id for v in page.videos]


def test_the_grid_leaves_out_what_was_watched_hidden_or_rejected():
    recommender = build([
        video("a", 97), video("b", 95), video("c", 93), video("d", 91, creator="Shouty"),
        video("e", 90), video("f", 89), video("g", 88),
    ])
    recommender.hidden_videos = {"f"}  # the quality filter
    store = Store(
        watch={"b": {"share": 0.9, "unmarked_at": None},       # watched
               "c": {"share": 0.4, "unmarked_at": None},       # started
               "e": {"share": 0.9, "unmarked_at": "2026-11-01"}},  # unmarked: back
        hides=[("video", "a"), ("channel", "Shouty")],
    )

    page = home.home(store, recommender, USER, "es")

    assert ids(page) == ["c", "e", "g"]
    assert page.total == 3
    started = page.videos[0]
    assert started.watched_share == 0.4 and started.understood == 93.0
    assert started.new_words == 7 and started.duration_s == 600
    assert page.videos[1].watched_share is None


def test_grammar_keeps_levels_up_to_the_filter_and_counts_every_level():
    recommender = build([
        video("a1", 99, grammar=1.2), video("a2", 98, grammar=3.9), video("b1", 97, grammar=4.0),
        video("b2", 96, grammar=7.5), video("c1", 95, grammar=9), video("none", 94),
    ])
    page = home.home(Store(), recommender, USER, "es", grammar="A2")

    assert ids(page) == ["a1", "a2"]
    assert page.levels == {"A1": 1, "A2": 1, "B1": 1, "B2": 1, "C1": 1}
    assert page.empty is None
    # Without the filter the unscored video shows too.
    assert "none" in ids(home.home(Store(), recommender, USER, "es"))


def test_a_language_without_scores_has_no_levels_and_ignores_the_filter():
    recommender = build([video("a", 99), video("b", 98)])
    page = home.home(Store(), recommender, USER, "es", grammar="A1")
    assert page.levels is None and ids(page) == ["a", "b"]


def test_a_topic_with_nothing_at_the_level_shows_where_it_starts():
    recommender = build([
        video("g1", 97, category="Gaming", grammar=5), video("g2", 99, category="Gaming", grammar=7),
        video("g3", 96, category="Gaming", grammar=5.5),
        video("t1", 95, category="Travel", grammar=3), video("t2", 94, category="Food", grammar=1),
        video("t3", 93, category="Food", grammar=5),
    ])
    page = home.home(Store(), recommender, USER, "es", topic="Gaming", grammar="A2")

    assert page.videos == [] and page.total == 0
    assert page.levels == {"A1": 0, "A2": 0, "B1": 2, "B2": 1, "C1": 0}
    assert page.empty.nearest_level == "B1"
    assert page.empty.nearest.count == 2
    assert [v.id for v in page.empty.nearest.videos] == ["g1", "g3"]
    assert page.empty.other.count == 2
    assert [v.id for v in page.empty.other.videos] == ["t1", "t2"]


def test_nothing_above_the_filter_either():
    recommender = build([video("g", 97, category="Gaming", grammar=1),
                         video("t", 95, category="Travel", grammar=9)])
    page = home.home(Store(), recommender, USER, "es", topic="Travel", grammar="A2")
    assert page.empty.nearest_level == "C1" and page.empty.other.count == 1
    page = home.home(Store(), recommender, USER, "es", topic="Gaming", grammar="C1")
    assert page.empty is None and ids(page) == ["g"]


def test_length_and_search_cut_the_grid():
    recommender = build([
        video("short", 99, length=300, creator="Ana Viaja"), video("mid", 98, length=900),
        video("long", 97, length=1500), video("unknown", 96, length=None),
    ])
    assert ids(home.home(Store(), recommender, USER, "es", length="short")) == ["short"]
    assert ids(home.home(Store(), recommender, USER, "es", length="medium")) == ["mid"]
    assert ids(home.home(Store(), recommender, USER, "es", length="long")) == ["long"]
    assert len(home.home(Store(), recommender, USER, "es").videos) == 4
    assert ids(home.home(Store(), recommender, USER, "es", query="  title MID ")) == ["mid"]
    assert ids(home.home(Store(), recommender, USER, "es", query="viaja")) == ["short"]


def test_following_shows_the_favourite_channels_videos():
    recommender = build([video("a", 99), video("b", 98), video("c", 97)])
    store = Store(favourites=[FOLLOWED], followed=["c", "a"])
    assert ids(home.home(store, recommender, USER, "es", topic="Following")) == ["a", "c"]
    assert ids(home.home(Store(), recommender, USER, "es", topic="Following")) == []


def test_channels_without_signals_are_the_best_understood_with_enough_videos():
    videos = (
        [video(f"e{i}", 96 + i % 3, creator="Easy") for i in range(5)]
        + [video(f"h{i}", 80, creator="Hard") for i in range(4)]
        + [video(f"s{i}", 99, creator="Small") for i in range(3)]   # too few
        + [video(f"m{i}", 90, creator="Mid") for i in range(4)]
        + [video(f"x{i}", 85, creator="Extra") for i in range(4)]
        + [video("nameless", 99)]
    )
    store = Store(favourites=[FOLLOWED], channel_ids={"e2": FOLLOWED, "m0": "UC" + "m" * 22})
    page = home.home(store, build(videos), USER, "es")

    assert [c.name for c in page.channels] == ["Easy", "Mid", "Extra"]
    easy = page.channels[0]
    assert easy.videos == 5 and easy.understood == pytest.approx(96.8)
    assert [v.understood for v in easy.best] == [98.0, 97.0, 97.0, 96.0]
    assert easy.channel_id == FOLLOWED and easy.following
    assert page.channels[1].channel_id == "UC" + "m" * 22 and not page.channels[1].following
    assert page.channels[2].channel_id is None

    # Every video here is Travel: the topic has the same channels; another has none.
    assert ([c.name for c in home.home(store, build(videos), USER, "es", topic="Travel").channels]
            == ["Easy", "Mid", "Extra"])
    assert home.home(store, build(videos), USER, "es", topic="Food").channels == []
    assert home.home(store, build(videos), USER, "es", query="e").channels == []
    assert home.home(store, build(videos), USER, "es", query="e").basis is None
    assert home.home(store, build(videos), USER, "es").basis == home.ChannelBasis(
        following=[], watched=0)


def look(channel, interest=5, trash=3):
    return {"look": {"channel": channel, "interest": interest, "trash": trash, "sensitive": "none"}}


def test_channels_you_might_like_weigh_what_the_judge_thinks_of_them():
    videos = (
        [video(f"c{i}", 97, creator="Clickbait") for i in range(10)]
        + [video(f"d{i}", 96, creator="Dull") for i in range(4)]
        + [video(f"g{i}", 92, creator="Good") for i in range(4)]
        + [video(f"t{i}", 90, creator="Taste", category="Food") for i in range(5)]
    )
    recommender = build(videos)
    recommender.video_signals = {"es": {
        # Most videos get through, but three in ten are rejected as trash.
        **{f"c{i}": look("Clickbait", trash=8 if i < 3 else 5) for i in range(10)},
        **{f"d{i}": look("Dull", interest=3) for i in range(4)},
        **{f"g{i}": look("Good", interest=8, trash=1) for i in range(4)},
        **{f"t{i}": look("Taste", interest=5) for i in range(5)},
    }}
    page = home.home(Store(), recommender, USER, "es")
    assert [c.name for c in page.channels] == ["Good", "Dull", "Taste"]
    # The channel's videos come in the grid's order.
    assert [v.id for v in page.channels[2].best] == ["t0", "t1", "t2", "t3"]


def subject_channel(name, subject, known, n=5, category="Travel"):
    return [video(f"{name}{i}", known, creator=name, category=category,
                  words=SUBJECTS[subject] if subject else ()) for i in range(n)]


def watched(*video_ids):
    return {v: {"video_id": v, "share": 0.95, "unmarked_at": None} for v in video_ids}


# Channels about nothing in particular, so a seed's lift has something to
# stand out from, as among the ~1,800 channels of es.
FILLER = [v for i in range(8) for v in subject_channel(f"filler{i}", None, 93)]


def test_channels_you_might_like_follow_your_favourites_and_history(monkeypatch):
    videos = (
        subject_channel("Marc", "ghosts", 90)       # a favourite
        + subject_channel("Trips", "trips", 90)     # watched once
        + subject_channel("Ghosts", "ghosts", 91)
        + subject_channel("Travels", "trips", 91)
        + subject_channel("Plain", None, 99)
        + FILLER
    )
    recommender = build(videos)
    marc = {f"Marc{i}" for i in range(5)}

    # Nothing to go on: the best understood, and the page is told so.
    page = home.home(Store(), recommender, USER, "es")
    assert page.channels[0].name == "Plain"
    assert all(c.because is None for c in page.channels)
    assert page.basis == home.ChannelBasis(following=[], watched=0)

    # A favourite about ghosts: the other ghost channel, said why. The
    # favourite itself isn't suggested.
    store = Store(favourites=[FOLLOWED], followed=marc)
    page = home.home(store, recommender, USER, "es")
    assert page.channels[0].name == "Ghosts" and page.channels[0].because == "Marc"
    assert "Marc" not in [c.name for c in page.channels]
    assert page.basis == home.ChannelBasis(following=["Marc"], watched=0)

    # A video watched from a travel channel: a watched channel weighs less
    # than a favourite, but the other travel channel comes in, and the
    # watched one stays out. Few channels here, so lifts are small.
    monkeypatch.setattr(home, "BECAUSE_LIFT", 1.5)
    store = Store(favourites=[FOLLOWED], followed=marc, watch=watched("Trips0"))
    page = home.home(store, recommender, USER, "es")
    names = [c.name for c in page.channels]
    assert {"Ghosts", "Travels"} <= set(names) and "Trips" not in names
    assert {c.name: c.because for c in page.channels}["Travels"] == "Trips"
    assert page.basis == home.ChannelBasis(following=["Marc"], watched=1)

    # Unmarked, it no longer counts.
    store = Store(watch={"Trips0": {"video_id": "Trips0", "share": 0.95,
                                    "unmarked_at": "2026-11-04T10:00:00Z"}})
    assert home.home(store, recommender, USER, "es").basis.watched == 0


def test_two_favourites_each_get_a_place(monkeypatch):
    monkeypatch.setattr(home, "CHANNELS", 2)
    videos = (
        subject_channel("Marc", "ghosts", 90) + subject_channel("Enrique", "trips", 90)
        + subject_channel("Ghosts", "ghosts", 97) + subject_channel("Haunted", "ghosts", 96)
        + subject_channel("Travels", "trips", 91) + FILLER
    )
    store = Store(favourites=[FOLLOWED],
                  followed={f"{name}{i}" for name in ("Marc", "Enrique") for i in range(5)})
    page = home.home(store, build(videos), USER, "es")
    # Haunted is better understood than Travels, but Ghosts already took Marc's place.
    assert [(c.name, c.because) for c in page.channels] == [
        ("Ghosts", "Marc"), ("Travels", "Enrique")]


def test_a_topic_suggests_its_own_channels_with_its_videos_first():
    videos = (
        subject_channel("Marc", "ghosts", 90)
        + subject_channel("Cook", "food", 95, category="Food")
        + [video("Cook9", 99, creator="Cook", category="Travel", words=SUBJECTS["food"])]
        + subject_channel("Chef", "food", 92, category="Food")
        + subject_channel("Ghosts", "ghosts", 91)
        + FILLER
    )
    store = Store(favourites=[FOLLOWED], followed={f"Marc{i}" for i in range(5)})
    page = home.home(store, build(videos), USER, "es", topic="Food")
    channels = {c.name: c for c in page.channels}
    assert set(channels) == {"Cook", "Chef"}
    # Cook9 is understood best but isn't Food: it comes after the Food ones.
    assert [v.id for v in channels["Cook"].best] == ["Cook0", "Cook1", "Cook2", "Cook3"]
    assert channels["Cook"].videos == 6
    assert page.basis.following == ["Marc"]
    # Following has no suggestions and no basis.
    following = home.home(store, build(videos), USER, "es", topic="Following")
    assert following.channels == [] and following.basis is None


def test_not_interested_hides_a_video_or_its_channel_and_undo_brings_it_back():
    a, b, c = "a" * 11, "b" * 11, "c" * 11
    recommender = build([video(a, 99, creator="Molaviajar"), video(b, 98, creator="Molaviajar"),
                         video(c, 97)])
    store = Store()

    one = HideRequest(language="es", video_id=a)
    assert home.set_hidden(store, recommender, USER, one, True).channel is None
    assert store.hidden == {("video", a)}
    assert ids(home.home(store, recommender, USER, "es")) == [b, c]
    home.set_hidden(store, recommender, USER, one, False)

    channel = HideRequest(language="es", video_id=a, channel=True)
    assert home.set_hidden(store, recommender, USER, channel, True).channel == "Molaviajar"
    assert ids(home.home(store, recommender, USER, "es")) == [c]
    assert home.set_hidden(store, recommender, USER, channel, False).channel == "Molaviajar"
    assert store.hidden == set()

    # A video the index doesn't know, or one without a channel name, hides nothing.
    for unknown in ("z" * 11, c):
        req = HideRequest(language="es", video_id=unknown, channel=True)
        assert home.set_hidden(store, recommender, USER, req, True).channel is None
    assert store.hidden == set()


def test_coming_back_reports_the_share_played_and_the_words_saved():
    since = datetime(2026, 11, 3, 12, tzinfo=UTC)
    store = Store(watch={"v": {"share": 0.42, "unmarked_at": None}}, saved=6)
    assert home.came_back(store, USER, "v", since) == home.Return(share=0.42, saved=6)
    assert store.saved_args == ("v", since)
    assert home.came_back(Store(), USER, "v", since) == home.Return(share=None, saved=0)


def test_level_of_cuts_halfway_between_levels():
    assert [home.level_of(g) for g in (1, 1.99, 2, 3.99, 4, 6, 8, 9, 10)] == [0, 0, 1, 1, 2, 3, 4, 4, 4]
    assert home.level_of(None) is None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    from app import app
    monkeypatch.setattr(auth, "verify_token", lambda t: SimpleNamespace(id=USER, is_anonymous=False))
    store = Store(saved=2)
    app.dependency_overrides[home.get_home_store] = lambda: store
    app.state.recommender = build([video("aaaaaaaaaaa", 99, creator="Ana", grammar=3)])
    yield TestClient(app), store
    app.dependency_overrides.clear()


AUTH = {"authorization": "Bearer ordinary-session"}


def test_the_page_route(client):
    http, _ = client
    response = http.get("/api/home?language=es&grammar=B1&length=medium", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["levels"] == {"A1": 0, "A2": 1, "B1": 0, "B2": 0, "C1": 0}
    response = http.get("/api/home?language=es", headers=AUTH)
    assert [v["id"] for v in response.json()["videos"]] == ["aaaaaaaaaaa"]
    assert http.get("/api/home?language=es&grammar=Z9", headers=AUTH).status_code == 422
    assert http.get("/api/home?language=es").status_code in (401, 403)


def test_the_hide_routes(client):
    http, store = client
    body = {"language": "es", "video_id": "aaaaaaaaaaa", "channel": True}
    assert http.post("/api/home/hide", json=body, headers=AUTH).json() == {"channel": "Ana"}
    assert store.hidden == {("channel", "Ana")}
    assert http.post("/api/home/unhide", json=body, headers=AUTH).json() == {"channel": "Ana"}
    assert store.hidden == set()
    bad = {"language": "es", "video_id": "not-an-id"}
    assert http.post("/api/home/hide", json=bad, headers=AUTH).status_code == 422


def test_the_return_route_needs_a_time_zone(client):
    http, _ = client
    ok = http.get("/api/home/return", params={"video_id": "aaaaaaaaaaa",
                                              "since": "2026-11-03T12:00:00+01:00"}, headers=AUTH)
    assert ok.json() == {"share": None, "saved": 2}
    naive = http.get("/api/home/return", params={"video_id": "aaaaaaaaaaa",
                                                 "since": "2026-11-03T12:00:00"}, headers=AUTH)
    assert naive.status_code == 422
