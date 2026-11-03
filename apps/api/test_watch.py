import json
import os
from datetime import UTC, date, datetime, timedelta

# supabase_client builds its client at import time; nothing here touches the network.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("REQUIRE_SERVICE_ROLE", "0")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.test-signature",
)

import pytest

import watch
from watch import DesktopWatch, HistoryItem, HistoryRead, RecapAdd, RecapPick, Unmark

USER = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
DAY = date(2026, 11, 1)
START = datetime(2026, 10, 31, 23, 0, tzinfo=UTC)  # Nov 1 in Berlin
END = datetime(2026, 11, 1, 23, 0, tzinfo=UTC)

# word_id -> (root, valid)
WORDS = {
    1: ("el", True), 2: ("alquiler", True), 3: ("la fianza", True), 4: ("el casero", True),
    5: ("pagar", True), 6: ("Pepe", False), 7: ("la nómina", True), 8: ("el piso", True),
}

A, B, C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


def tokens(*words):
    """Transcript content: a word id per word, punctuation as given."""
    out = []
    for w in words:
        if isinstance(w, int):
            out += [{"content": WORDS[w][0], "id": w}, {"content": " "}]
        else:
            out.append({"content": w})
    return out


class FakeVocab:
    def __init__(self, statuses):
        self.list = dict(statuses)
        self.events = []
        self.added = []

    def statuses(self, user_id, word_ids):
        return {w: self.list[w] for w in word_ids if w in self.list}

    def words(self, word_ids):
        return {w: {"id": w, "root": WORDS[w][0]} for w in word_ids if w in WORDS}

    def exposed(self, user_id, media, word_ids, kind="exposure"):
        return {e["word_id"] for e in self.events
                if e["kind"] == kind and e["context"]["media"] == media}

    def insert_events(self, rows):
        self.events.extend(rows)
        return len(rows)

    def add_words(self, user_id, word_ids, status, source="chatgpt"):
        self.added.append((word_ids, status, source))
        self.list.update(dict.fromkeys(word_ids, status))


class FakeStore:
    def __init__(self, rows=(), statuses=None, closed=None):
        self.data = {r["video_id"]: {"unmarked_at": None, "share": None, "source": "desktop",
                                     "language": "es", "created_at": "2026-10-01T00:00:00+00:00",
                                     **r} for r in rows}
        self.vocab = FakeVocab(statuses or {})
        self.closed = closed
        self.history_deleted = False

    def rows(self, user_id, video_ids):
        return {v: dict(self.data[v]) for v in video_ids if v in self.data}

    def write(self, user_id, language, video_id, fields):
        # Like the real upsert: Postgres checks not-null on the insert half
        # before it sees the conflict, so an existing row doesn't excuse it.
        assert "source" in fields, "null value in column source"
        row = self.data.setdefault(video_id, {"video_id": video_id, "unmarked_at": None,
                                              "share": None, "source": "history",
                                              "created_at": NOW.isoformat()})
        row.update({"language": language, **fields})

    def unmark(self, user_id, video_id, now):
        if video_id in self.data and self.data[video_id]["unmarked_at"] is None:
            self.data[video_id]["unmarked_at"] = now.isoformat()

    def delete_history(self, user_id):
        self.data = {v: r for v, r in self.data.items() if r["source"] != "history"}

    def watched_between(self, user_id, language, start, end):
        return [dict(r) for r in self.data.values()
                if r.get("watched_at") and r["language"] == language
                and start <= datetime.fromisoformat(r["watched_at"]) < end]

    def recent(self, user_id, language, limit):
        return [dict(r) for r in self.data.values()
                if r["language"] == language and r["unmarked_at"] is None][:limit]

    def valid_words(self, word_ids):
        return {w: WORDS[w][0] for w in word_ids if w in WORDS and WORDS[w][1]}

    def closed_on(self, user_id):
        return self.closed

    def close(self, user_id, day):
        self.closed = day


@pytest.fixture
def videos(corpus, monkeypatch):
    """Three indexed Spanish videos; anything else is not in the index."""
    monkeypatch.setattr(watch, "_now", lambda: NOW)
    watch._read.cache_clear()

    def put(video_id, content, length=600, title="Un vídeo"):
        (corpus / f"{video_id}_processed.json").write_text(json.dumps(
            {"id": video_id, "title": title, "length": length, "content": content}))

    put(A, tokens(1, 2, 3, ".", 1, 4, 4, 4, ".", 6, 6, 6, "."), title="Buscar piso")
    put(B, tokens(1, 2, 3, 5, "?", 7, 8, "."), length=1200)
    put(C, tokens(1, 5, 8, "."))
    return put


def at(day_offset=0):
    return (NOW - timedelta(days=day_offset)).isoformat()


# --- watched or not --------------------------------------------------------

def test_watched_means_70_percent_or_unknown_share():
    assert watch.is_watched({"share": 0.7, "source": "history", "unmarked_at": None})
    assert watch.is_watched({"share": None, "source": "history", "unmarked_at": None})
    assert not watch.is_watched({"share": 0.69, "source": "history", "unmarked_at": None})
    assert not watch.is_watched({"share": 1.0, "source": "desktop", "unmarked_at": at()})


# --- desktop ---------------------------------------------------------------

def test_desktop_watch_of_an_indexed_video_is_stored(videos):
    store = FakeStore()
    result = watch.record_desktop(store, USER, DesktopWatch(video_id=A, language="es", share=0.72))
    assert result.model_dump() == {"indexed": True, "watched": True}
    assert (store.data[A]["source"], store.data[A]["share"], store.data[A]["watched_at"]) == \
        ("desktop", 0.72, NOW.isoformat())


def test_desktop_watch_outside_the_index_stores_nothing(videos):
    store = FakeStore()
    result = watch.record_desktop(store, USER, DesktopWatch(video_id="zzzzzzzzzzz", language="es", share=0.9))
    assert result.model_dump() == {"indexed": False, "watched": False}
    # Indexed in Spanish is not indexed in Italian.
    assert not watch.record_desktop(store, USER, DesktopWatch(video_id=A, language="it", share=0.9)).watched
    assert store.data == {}


def test_desktop_watch_needs_70_percent():
    with pytest.raises(ValueError):
        DesktopWatch(video_id=A, language="es", share=0.5)


def test_unmark_then_watch_again_on_desktop_marks_it_again(videos):
    store = FakeStore([{"video_id": A, "share": 0.95, "watched_at": at(3)}])
    assert watch.status(store, USER, "es", A).watched
    watch.unmark(store, USER, Unmark(video_id=A))
    assert not watch.status(store, USER, "es", A).watched
    # The retry counts from what was played this time, not the old 95%.
    watch.record_desktop(store, USER, DesktopWatch(video_id=A, language="es", share=0.7))
    assert watch.status(store, USER, "es", A).watched
    assert store.data[A]["share"] == 0.7


# --- history page ----------------------------------------------------------

def history(*items):
    return HistoryRead(language="es", items=[HistoryItem(**i) for i in items])


def test_history_keeps_only_indexed_videos_in_the_language(videos):
    store = FakeStore()
    kept, heard = watch.record_history(store, USER, history(
        {"video_id": A, "share": 1.0, "day": 0},
        {"video_id": "notindexed1", "share": 1.0, "day": 0},
        {"video_id": "xxxxxxxxxxx", "share": 0.4, "day": 1},
    ))
    assert kept.kept == 1
    assert set(store.data) == {A}
    assert heard == [A]


def test_history_dates_today_and_yesterday_and_leaves_earlier_days_undated(videos):
    store = FakeStore()
    watch.record_history(store, USER, history(
        {"video_id": A, "share": 0.9, "day": 0},
        {"video_id": B, "share": 0.9, "day": 1},
        {"video_id": C, "share": 0.9},
    ))
    assert store.data[A]["watched_at"] == at(0)
    assert store.data[B]["watched_at"] == at(1)
    assert store.data[C]["watched_at"] is None


def test_history_under_70_percent_is_kept_but_not_watched_until_the_bar_grows(videos):
    store = FakeStore()
    _, heard = watch.record_history(store, USER, history({"video_id": A, "share": 0.3, "day": 1}))
    assert not watch.status(store, USER, "es", A).watched and heard == []
    _, heard = watch.record_history(store, USER, history({"video_id": A, "share": 0.8, "day": 0}))
    assert watch.status(store, USER, "es", A).watched and heard == [A]
    assert store.data[A]["watched_at"] == at(0)


def test_history_never_shrinks_a_share_or_moves_a_watch(videos):
    store = FakeStore([{"video_id": A, "share": 0.9, "watched_at": at(5), "source": "desktop"}])
    _, heard = watch.record_history(store, USER, history({"video_id": A, "share": 0.5, "day": 0}))
    assert heard == []
    assert (store.data[A]["share"], store.data[A]["watched_at"], store.data[A]["source"]) == \
        (0.9, at(5), "desktop")


def test_an_unmarked_video_stays_unmarked_on_the_next_history_read(videos):
    store = FakeStore([{"video_id": A, "share": 0.9, "watched_at": at(2), "unmarked_at": at(1),
                        "source": "history"}])
    watch.record_history(store, USER, history({"video_id": A, "share": 0.9, "day": None}))
    assert not watch.status(store, USER, "es", A).watched


def test_an_unmarked_video_the_user_quit_comes_back_when_rewatched(videos):
    # Unmarked with the bar at 30%; then watched to the end on the phone.
    store = FakeStore([{"video_id": A, "share": 0.3, "watched_at": None, "unmarked_at": at(2),
                        "source": "history"}])
    _, heard = watch.record_history(store, USER, history({"video_id": A, "share": 1.0, "day": 0}))
    assert watch.status(store, USER, "es", A).watched and heard == [A]


def test_an_unmarked_desktop_watch_stays_unmarked_whatever_the_bar_says(videos):
    # Marked at 70% and played to the end, then unmarked before the next
    # history read: the bar shows that same viewing.
    store = FakeStore([{"video_id": A, "share": 0.7, "watched_at": at(0), "unmarked_at": at(0),
                        "source": "desktop"}])
    _, heard = watch.record_history(store, USER, history({"video_id": A, "share": 1.0, "day": 0}))
    assert not watch.status(store, USER, "es", A).watched and heard == []


def test_turning_history_off_deletes_its_rows_only(videos):
    store = FakeStore([{"video_id": A, "source": "history"}, {"video_id": B, "source": "desktop"}])
    watch.turn_off_history(store, USER)
    assert set(store.data) == {B}


# --- heard words -----------------------------------------------------------

def test_learning_words_of_a_watched_video_count_as_heard_once(videos):
    store = FakeStore(statuses={2: "learning", 3: "known", 4: "learning", 6: "learning"})
    assert watch.record_heard(store, USER, "es", A) == 3
    assert {e["word_id"] for e in store.vocab.events} == {2, 4, 6}
    assert {(e["kind"], e["source"], e["context"]["media"]) for e in store.vocab.events} == \
        {("exposure", "video", f"youtube:{A}")}
    assert watch.record_heard(store, USER, "es", A) == 0


# --- recap -----------------------------------------------------------------

def recap(store):
    return watch.recap(store, USER, "es", DAY, START, END)


def test_recap_lists_new_words_from_two_videos_or_said_three_times(videos):
    store = FakeStore([{"video_id": A, "share": 1.0, "watched_at": at(1)},
                       {"video_id": B, "share": 0.75, "watched_at": at(1), "source": "history"}],
                      statuses={1: "known"})
    r = recap(store)
    assert (r.videos, r.minutes) == (2, 25)  # 10 min + 75% of 20 min
    # 2 and 3 in both videos; 4 three times in A; 6 is a name; 1 is known;
    # 5, 7, 8 came up once.
    assert [(w.word, w.video_id) for w in r.words] == \
        [("alquiler", A), ("la fianza", A), ("el casero", A)]


def test_recap_shows_at_most_eight_words(videos):
    many = tokens(*[w for w in WORDS if WORDS[w][1]], ".")
    videos(A, many)
    videos(B, many)
    store = FakeStore([{"video_id": A, "watched_at": at(1)}, {"video_id": B, "watched_at": at(1)}])
    watch.RECAP_WORDS, old = 3, watch.RECAP_WORDS
    try:
        assert len(recap(store).words) == 3
    finally:
        watch.RECAP_WORDS = old


def test_no_recap_without_qualifying_words(videos):
    store = FakeStore([{"video_id": C, "watched_at": at(1)}])
    assert recap(store).words == []


def test_recap_leaves_out_other_days_unmarked_and_quit_videos(videos):
    store = FakeStore([
        {"video_id": A, "watched_at": at(0)},                      # today
        {"video_id": B, "watched_at": at(1), "unmarked_at": at()},  # unmarked
        {"video_id": C, "watched_at": at(1), "share": 0.2, "source": "history"},
    ])
    assert recap(store).videos == 0


def test_not_now_puts_away_that_days_recap_only(videos):
    store = FakeStore([{"video_id": A, "watched_at": at(1)}, {"video_id": B, "watched_at": at(1)}])
    watch.close_recap(store, USER, watch.RecapClose(day=DAY))
    assert recap(store).words == []
    assert watch.recap(store, USER, "es", date(2026, 11, 2), START, END).words


# --- adding ----------------------------------------------------------------

def test_added_words_go_in_as_learning_with_the_video_and_a_sentence(videos):
    store = FakeStore([{"video_id": A, "watched_at": at(1)}, {"video_id": B, "watched_at": at(1)}])
    added = watch.add_recap_words(store, USER, RecapAdd(language="es", words=[
        RecapPick(word_id=4, video_id=A), RecapPick(word_id=7, video_id=B),
    ]))
    assert added.added == ["el casero", "la nómina"]
    assert store.vocab.added == [([4], "learning", A), ([7], "learning", B)]
    assert store.vocab.events == [
        {"user_id": USER, "word_id": 4, "kind": "saved", "source": "video",
         "context": {"site": "youtube", "media": f"youtube:{A}", "title": "Buscar piso",
                     "sentence": "el el casero el casero el casero ."}},
        {"user_id": USER, "word_id": 7, "kind": "saved", "source": "video",
         "context": {"site": "youtube", "media": f"youtube:{B}", "title": "Un vídeo",
                     "sentence": "la nómina el piso ."}},
    ]


def test_adding_skips_words_listed_already_not_in_the_video_or_of_unwatched_videos(videos):
    store = FakeStore([{"video_id": A, "watched_at": at(1)},
                       {"video_id": B, "watched_at": at(1), "unmarked_at": at()}],
                      statuses={2: "learning"})
    added = watch.add_recap_words(store, USER, RecapAdd(language="es", words=[
        RecapPick(word_id=2, video_id=A),  # in the list
        RecapPick(word_id=7, video_id=A),  # not said in A
        RecapPick(word_id=5, video_id=B),  # B was unmarked
        RecapPick(word_id=6, video_id=A),  # not vocabulary
    ]))
    assert added.added == [] and store.vocab.added == [] and store.vocab.events == []


def test_sentence_prefers_one_of_a_good_length():
    doc = {"content": tokens(2, ".", 1, 2, 3, 5, 7, 8, ".")}
    assert watch.sentence_with(doc, 2) == "el alquiler la fianza pagar la nómina el piso ."
    assert watch.sentence_with(doc, 4) is None


def test_sentence_without_punctuation_is_the_words_around_it():
    # Auto-captions: one unpunctuated run; the word far from its start.
    doc = {"content": tokens(*([1, 5] * 20), 7, *([8, 2] * 20))}
    sentence = watch.sentence_with(doc, 7)
    assert "la nómina" in sentence
    assert len(sentence.split()) <= 2 * watch.SENTENCE_WORDS[1]
    assert sentence.startswith("pagar") or sentence.startswith("el")


# --- watched list ----------------------------------------------------------

def test_watched_list_is_newest_first_with_titles_and_leaves_out_unwatched(videos):
    store = FakeStore([{"video_id": A, "watched_at": at(2)},
                       {"video_id": B, "watched_at": at(0)},
                       {"video_id": C, "watched_at": at(1), "share": 0.2, "source": "history"}])
    listed = watch.watched_list(store, USER, "es").videos
    assert [(v.video_id, v.title) for v in listed] == [(B, "Un vídeo"), (A, "Buscar piso")]
