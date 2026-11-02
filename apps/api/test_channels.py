"""channels.py: favourites, a channel's progress line, videos at your level,
core words. The queue parts run the real ChannelStore against the shared
video_queue fake (conftest.py); the rest against an in-memory store."""

import json
import os

# supabase_client builds its client at import time; nothing here touches the network.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("REQUIRE_SERVICE_ROLE", "0")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("DEEPINFRA_API_KEY", "test-key")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.test-signature",
)

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.sparse import csr_matrix

import channels
from conftest import FakeSupabase, queued

USER = "11111111-1111-1111-1111-111111111111"
CHANNEL = "UC" + "a" * 22
NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)

# Word ids: 1-4 everyday words the learner knows, 5 "el cofre" in every video,
# 6 "la corona" in two of six, 7 "la chispa" in four, already learning,
# 8 a name the dictionary marks invalid, 9 "el mago" in three of six.
ROOTS = {5: "el cofre", 6: "la corona", 9: "el mago"}
KNOWN = {1, 2, 3, 4}


def video(**spoken):
    return {int(k[1:]): v for k, v in spoken.items()}


VIDEOS = {
    "v1": video(w1=40, w2=30, w3=10, w5=8, w7=2, w8=3, w9=1),
    "v2": video(w1=40, w2=30, w4=10, w5=6, w6=4, w7=2, w8=3, w9=1),
    "v3": video(w1=40, w2=30, w3=10, w5=7, w6=4, w7=2, w8=3, w9=1),
    "v4": video(w1=40, w2=30, w4=10, w5=5, w7=2, w8=3),
    "v5": video(w1=40, w2=30, w3=10, w5=9, w8=3),
    "v6": video(w1=40, w2=30, w4=10, w5=5, w8=3),
    "other": video(w1=5, w6=50),    # another channel
    "hidden": video(w5=99),         # garbled captions
}


def recommender(videos=VIDEOS):
    names = list(videos)
    data, indices, indptr = [], [], [0]
    for name in names:
        for word, count in sorted(videos[name].items()):
            indices.append(word)
            data.append(count)
        indptr.append(len(indices))
    counts = csr_matrix((np.array(data, dtype=np.int16), indices, indptr), shape=(len(names), 12))
    presence = csr_matrix((np.ones(counts.nnz, dtype=np.int8), counts.indices, counts.indptr),
                          shape=counts.shape)
    return SimpleNamespace(
        languages=["es"], _ensure_language_loaded=lambda language: None,
        filenames={"es": [f"{n}_processed.json" for n in names]},
        matrices={"es": counts}, presence={"es": presence},
        distinct_words_per_doc={"es": np.diff(counts.indptr)},
    )


@pytest.fixture(autouse=True)
def short_videos_count(monkeypatch):
    monkeypatch.setattr(channels, "MIN_DISTINCT_WORDS", 1)
    monkeypatch.setattr(channels, "worker_language", lambda: "es")
    channels._rows_by_video.clear()
    channels._listings.clear()


class Store(channels.ChannelStore):
    """The real queue queries on the video_queue fake; the user's words,
    the dictionary and favourites in memory."""

    def __init__(self, queue=(), known=KNOWN, listed=(7,), favourited_at=None, from_channel=()):
        super().__init__(FakeSupabase(queue))
        self.known, self.listed = set(known), set(listed)
        self.from_channel = list(from_channel)
        self.favourites = {} if favourited_at is None else {(USER, CHANNEL): favourited_at}

    def favourited_at(self, user_id, channel_id):
        return self.favourites.get((user_id, channel_id))

    def favourite(self, user_id, channel_id, language):
        new = (user_id, channel_id) not in self.favourites
        self.favourites.setdefault((user_id, channel_id), NOW)
        return new

    def added_from_channel(self, user_id, channel_id):
        return self.from_channel

    def unfavourite(self, user_id, channel_id):
        self.favourites.pop((user_id, channel_id), None)

    def known_words(self, user_id):
        return self.known

    def listed_words(self, user_id):
        return self.listed

    def broken(self, video_ids):
        return {"hidden"} & set(video_ids)

    def valid_words(self, word_ids):
        return {w: ROOTS[w] for w in word_ids if w in ROOTS}


def done(video_id, **kw):
    return queued(video_id, **{"status": "done", "channel_id": CHANNEL,
                               "done_at": (NOW - timedelta(hours=2)).isoformat(), **kw})


CHANNEL_DONE = [done(f"v{n}") for n in range(1, 7)] + [done("hidden")]


def view(store, rec=None):
    return channels.channel_view(store, rec or recommender(), USER, CHANNEL, "es", now=NOW)


# ------------------------------------------------------------ core words ──

def test_core_words_are_unlisted_valid_words_in_half_the_videos_most_spoken_first():
    result = view(Store(CHANNEL_DONE)).core_words
    # 5 is in all six videos, 9 in three: half. 6 is in two, 7 is already
    # learning, 8 isn't vocabulary, and the hidden video counts for nothing.
    assert [(w.word_id, w.word) for w in result.words] == [(5, "el cofre"), (9, "el mago")]
    spoken = sum(sum(VIDEOS[f"v{n}"].values()) for n in range(1, 7))
    heard = sum(c for n in range(1, 7) for w, c in VIDEOS[f"v{n}"].items() if w in KNOWN)
    assert result.before == round(heard / spoken * 100, 1)
    assert result.after == round((heard + 40 + 3) / spoken * 100, 1)


def test_no_card_for_a_small_gain_or_a_handful_of_videos(monkeypatch):
    monkeypatch.setattr(channels, "CORE_MIN_GAIN", 0.2)
    assert view(Store(CHANNEL_DONE)).core_words is None
    monkeypatch.setattr(channels, "CORE_MIN_GAIN", 0.03)
    assert view(Store(CHANNEL_DONE[:4])).core_words is None


def test_counts_videos_at_your_level_from_indexed_rows_only():
    store = Store([*CHANNEL_DONE, queued("v7", channel_id=CHANNEL)], known=KNOWN | {5})
    result = view(store)
    # v7 is still pending and the hidden video never counts.
    expected = sum(1 for n in range(1, 7)
                   if sum(c for w, c in VIDEOS[f"v{n}"].items() if w in KNOWN | {5})
                   >= 0.95 * sum(VIDEOS[f"v{n}"].values()))
    assert result.videos == 6 and result.at_level == expected
    assert expected > 0


def test_a_channel_nothing_indexed_from_shows_nothing():
    result = view(Store([queued("v1", channel_id=CHANNEL)]))
    assert result == channels.ChannelView(favourite=False, videos=0, at_level=0,
                                          progress=None, core_words=None)


# -------------------------------------------------------------- progress ──

def test_progress_counts_done_and_waiting_rows_while_videos_are_to_come():
    rows = [done("a"), done("b"), queued("c", channel_id=CHANNEL),
            queued("d", channel_id=CHANNEL, status="processing"),
            queued("e", channel_id=CHANNEL, attempts=3),   # never claimed again
            queued("f", channel_id=CHANNEL, status="failed")]
    assert channels.progress(rows, NOW - timedelta(hours=3), NOW) == channels.Progress(added=2, total=4)
    assert channels.progress(rows, None, NOW) is None


def test_progress_drops_the_total_once_nothing_finished_for_a_day():
    stale = [done("a", done_at=(NOW - timedelta(days=2)).isoformat()), queued("c", channel_id=CHANNEL)]
    assert channels.progress(stale, NOW - timedelta(days=3), NOW) == channels.Progress(added=1, total=None)
    # A fresh favourite is not stalled, however old its done rows.
    assert channels.progress(stale, NOW - timedelta(hours=1), NOW).total == 2


def test_progress_disappears_once_the_channel_is_done():
    assert channels.progress([done("a"), done("b")], NOW - timedelta(hours=1), NOW) is None


# ------------------------------------------------------------- favourite ──

def test_favouriting_moves_the_channels_pending_discovery_rows_to_the_user_tier():
    store = Store([queued("a", channel_id=CHANNEL), queued("b", channel_id=CHANNEL, status="done"),
                   queued("c", channel_id=CHANNEL, source="manual", priority=20),
                   queued("d", channel_id="UC" + "b" * 22),
                   queued("e", channel_id=CHANNEL, lang="fr")])
    assert channels.set_favourite(store, USER, CHANNEL, "es", True) is True
    q = store.db
    assert q.row("a")["priority"] == 10
    # Source user, so `ytpipeline select --push` keeps the row.
    assert q.row("a")["source"] == "user" and q.row("a")["submitted_by"] == USER
    assert q.row("b")["priority"] == 0 and q.row("c")["priority"] == 20
    assert q.row("d")["priority"] == 0 and q.row("e")["priority"] == 0
    assert view(store).favourite


def test_unfavouriting_leaves_the_queue_alone():
    store = Store([queued("a", channel_id=CHANNEL, source="user", priority=10)], favourited_at=NOW)
    assert channels.set_favourite(store, USER, CHANNEL, "es", False) is False
    assert store.db.row("a")["priority"] == 10
    assert not view(store).favourite


def test_favouriting_again_is_not_a_new_favourite():
    store = Store([queued("a", channel_id=CHANNEL)], favourited_at=NOW)
    assert channels.set_favourite(store, USER, CHANNEL, "es", True) is False
    assert store.db.row("a")["priority"] == 0


def test_queues_new_uploads_only_most_viewed_first():
    store = Store([queued("old", channel_id=CHANNEL, status="done")])
    uploads = [{"video_id": "old", "title": "Old", "duration_s": 600, "views": 50},
               {"video_id": "new", "title": "New", "duration_s": 900, "views": 200}]
    assert channels.queue_uploads(store, USER, CHANNEL, "es", uploads) == 1
    new = store.db.row("new")
    assert (new["priority"], new["source"], new["score"]) == (10, "user", 1.0)
    assert new["channel_id"] == CHANNEL and new["submitted_by"] == USER and new["lang"] == "es"
    assert store.db.row("old")["status"] == "done"


class Response:
    def __init__(self, body, status_code=200):
        self.body, self.status_code = body, status_code

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def youtube(pages, items):
    calls = []

    def get(url, params, headers, timeout):
        assert headers == {"X-Goog-Api-Key": "key"}
        calls.append((url.rsplit("/", 1)[1], params))
        if url.endswith("playlistItems"):
            return pages[params.get("pageToken", "")]
        return Response({"items": [items[i] for i in params["id"].split(",") if i in items]})
    return get, calls


def item(video_id, duration, live="none", audio=None):
    snippet = {"title": f" {video_id} ", "liveBroadcastContent": live}
    if audio:
        snippet["defaultAudioLanguage"] = audio
    return {"id": video_id, "snippet": snippet,
            "contentDetails": {"duration": duration}, "statistics": {"viewCount": "7"}}


def test_fetches_uploads_and_keeps_the_ones_a_learner_would_watch():
    pages = {"": Response({"items": [{"contentDetails": {"videoId": "a"}},
                                     {"contentDetails": {"videoId": "short"}}],
                           "nextPageToken": "p2"}),
             "p2": Response({"items": [{"contentDetails": {"videoId": "live"}},
                                       {"contentDetails": {"videoId": "long"}}]})}
    items = {"a": item("a", "PT12M3S", audio="es-419"), "short": item("short", "PT45S"),
             "live": item("live", "PT20M", live="live"), "long": item("long", "PT2H")}
    get, calls = youtube(pages, items)
    assert channels.fetch_uploads(CHANNEL, "key", get) == [
        {"video_id": "a", "title": "a", "duration_s": 723, "views": 7, "audio": "es"}]
    # The key travels in a header, so no error message can carry it to the logs.
    assert calls[0] == ("playlistItems", {"part": "contentDetails", "playlistId": "UU" + "a" * 22,
                                          "maxResults": 50})
    assert all("key" not in params for _, params in calls)
    assert [c[0] for c in calls] == ["playlistItems", "playlistItems", "videos"]


def test_a_channel_without_uploads_queues_nothing():
    get, _ = youtube({"": Response({}, status_code=404)}, {})
    assert channels.fetch_uploads(CHANNEL, "key", get) == []


def upload(video_id, audio="", title="un título"):
    return {"video_id": video_id, "title": title, "duration_s": 600, "views": 1, "audio": audio}


ENGLISH_TITLES = "How I built a house in the woods with my own hands and what it cost me " * 6
SPANISH_TITLES = "Cómo construí una casa en el bosque con mis propias manos y cuánto me costó " * 6


def test_a_channel_in_another_language_queues_nothing():
    english = [upload(str(n), "en") for n in range(4)]
    assert channels.in_language(english, "es", vetted=False) == []
    assert channels.in_language([upload("a", title=ENGLISH_TITLES)], "es", vetted=False) == []


def test_a_channel_in_the_language_queues_and_drops_the_audio_field():
    spanish = [upload(str(n), "es") for n in range(4)]
    assert [v["video_id"] for v in channels.in_language(spanish, "es", vetted=False)] == list("0123")
    assert "audio" not in channels.in_language(spanish, "es", vetted=False)[0]
    assert len(channels.in_language([upload("a", title=SPANISH_TITLES)], "es", vetted=False)) == 1


def test_a_channel_with_transcripts_skips_the_channel_check_but_not_the_videos():
    mixed = [upload("en", "en"), upload("es", "es"), upload("unstated")]
    assert [v["video_id"] for v in channels.in_language(mixed, "es", vetted=True)] == ["es", "unstated"]


def test_uploads_are_listed_only_for_the_language_the_worker_drains(monkeypatch):
    monkeypatch.setattr(channels, "fetch_uploads", lambda *a: pytest.fail("nothing drains de"))
    assert channels.queue_channel(Store(), USER, CHANNEL, "de", "key") == 0
    monkeypatch.setattr(channels, "worker_language", lambda: None)
    assert channels.queue_channel(Store(), USER, CHANNEL, "es", "key") == 0


def test_progress_only_shows_for_the_language_the_worker_drains(monkeypatch):
    store = Store([done("a"), queued("b", channel_id=CHANNEL)], favourited_at=NOW - timedelta(hours=1))
    assert view(store).progress == channels.Progress(added=1, total=2)
    monkeypatch.setattr(channels, "worker_language", lambda: "de")
    assert view(store).progress is None


def test_listings_are_limited_per_user(monkeypatch):
    calls = []
    monkeypatch.setattr(channels, "fetch_uploads", lambda *a: calls.append(a) or [])
    monkeypatch.setattr(channels, "LISTINGS_PER_DAY", 2)
    for _ in range(3):
        channels.queue_channel(Store(), USER, CHANNEL, "es", "key")
    assert len(calls) == 2
    channels.queue_channel(Store(), "someone else", CHANNEL, "es", "key")
    assert len(calls) == 3
    # A day later the allowance is back.
    assert channels._may_list(USER, now=channels.time.monotonic() + 86401)


def test_no_uploads_are_listed_while_the_users_rows_wait(monkeypatch):
    monkeypatch.setattr(channels, "fetch_uploads", lambda *a: pytest.fail("over the limit"))
    monkeypatch.setattr(channels, "MAX_WAITING", 2)
    waiting = [queued(str(n), submitted_by=USER) for n in range(2)]
    assert channels.queue_channel(Store(waiting), USER, CHANNEL, "es", "key") == 0


def test_without_an_api_key_a_favourite_only_promotes(monkeypatch):
    monkeypatch.setattr(channels, "fetch_uploads", lambda *a: pytest.fail("no key, no call"))
    assert channels.queue_channel(Store(), USER, CHANNEL, "es", None) == 0


def test_a_youtube_failure_never_fails_the_favourite(monkeypatch):
    def boom(*_):
        raise RuntimeError("quota")
    monkeypatch.setattr(channels, "fetch_uploads", boom)
    assert channels.queue_channel(Store(), USER, CHANNEL, "es", "key") == 0


# ------------------------------------------------------ core words added ──

class Vocab:
    def __init__(self, fail_events=False):
        self.added, self.events, self.fail_events = [], [], fail_events

    def add_words(self, user_id, word_ids, status, source):
        self.added.append((user_id, word_ids, status, source))

    def insert_events(self, rows):
        if self.fail_events:
            raise RuntimeError("supabase down")
        self.events += rows
        return len(rows)


def test_adds_core_words_as_learning_with_a_line_from_the_channel(corpus):
    tokens = []
    for n, word in enumerate(["abrimos", "el", "cofre", "legendario", "y", "sale", "un", "mago"]):
        tokens += [{"content": word, "id": {2: 5, 7: 9}.get(n, 1)}, {"content": " "}]
    (corpus / "v1_processed.json").write_text(json.dumps({"title": "Cofres", "content": tokens}))

    vocab = Vocab()
    result = channels.add_core_words(Store(CHANNEL_DONE), vocab, recommender(), USER, CHANNEL, "es")
    assert result.added == ["el cofre", "el mago"]
    assert vocab.added == [(USER, [5, 9], "learning", CHANNEL)]
    cofre, mago = vocab.events
    assert cofre["kind"] == "saved" and cofre["source"] == "video" and cofre["word_id"] == 5
    assert cofre["context"] == {"site": "youtube", "channel_id": CHANNEL, "media": "youtube:v1",
                                "title": "Cofres",
                                "sentence": "abrimos el cofre legendario y sale un mago"}
    assert mago["context"]["media"] == "youtube:v1"


def test_a_failed_add_leaves_nothing_and_can_be_retried():
    vocab = Vocab(fail_events=True)
    with pytest.raises(RuntimeError):
        channels.add_core_words(Store(CHANNEL_DONE), vocab, recommender(), USER, CHANNEL, "es")
    assert vocab.added == []


def test_adding_again_answers_with_the_first_batch_and_adds_no_more():
    vocab = Vocab()
    store = Store(CHANNEL_DONE, from_channel=["el cofre", "el mago"])
    assert channels.add_core_words(store, vocab, recommender(), USER, CHANNEL, "es").added == [
        "el cofre", "el mago"]
    assert vocab.added == [] and vocab.events == []


def test_the_card_goes_once_its_words_are_added():
    assert view(Store(CHANNEL_DONE, from_channel=["el cofre"])).core_words is None


def test_context_lines_skip_tokens_that_are_not_words(corpus):
    tokens = [{"content": "el ", "id": 1}, "stray", {"content": "cofre", "id": 5}]
    (corpus / "v1_processed.json").write_text(json.dumps({"title": "t", "content": tokens}))
    rec = recommender()
    lines = channels.context_lines("es", [5], [("v1", 0)], rec.presence["es"])
    assert lines[5]["sentence"] == "el cofre"


def test_adds_nothing_when_the_channel_has_no_card():
    vocab = Vocab()
    assert channels.add_core_words(Store(CHANNEL_DONE[:3]), vocab, recommender(), USER,
                                   CHANNEL, "es").added == []
    assert vocab.added == [] and vocab.events == []


class Scores:
    """video_scores, just enough for ChannelStore.broken's one query."""

    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "video_scores"
        return self

    def select(self, _columns):
        return self

    def in_(self, column, ids):
        self.ids = set(ids)
        return self

    def execute(self):
        return SimpleNamespace(data=[r for r in self.rows if r["video_id"] in self.ids])


def scores(video_id, **kw):
    return {"video_id": video_id, "p_garbled": 0.0, "p_foreign_lesson": 0.0, "p_sung": 0.0,
            "content": 8, "transferable": 8, **kw}


def test_a_chosen_channel_keeps_videos_the_scores_only_found_dull():
    store = channels.ChannelStore(Scores([
        scores("fine"), scores("dull", content=1, transferable=1), scores("garbled", p_garbled=0.99),
        scores("song", p_sung=0.99), scores("lesson", p_foreign_lesson=0.99)]))
    assert store.broken(["fine", "dull", "garbled", "song", "lesson", "unscored"]) == {
        "garbled", "song", "lesson"}
