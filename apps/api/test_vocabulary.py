import os

# supabase_client builds its client at import time; nothing here touches the network.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("REQUIRE_SERVICE_ROLE", "0")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.test-signature",
)

import vocabulary

USER = "11111111-1111-1111-1111-111111111111"

# token -> (word_id, status), as classify_words_for would answer for USER
CLASSES = {
    "El": (1, "known"), "perro": (2, "learning"), "come": (3, "known"),
    "la": (4, "known"), "manzana": (5, "new"), "casa": (6, "ignored"),
}
WORDS = {1: "el", 2: "el perro", 3: "comer", 4: "la", 5: "la manzana", 6: "la casa"}


class FakeStore:
    def __init__(self, recalls=()):
        self.calls = []
        self.events = []
        self.recalls = list(recalls)

    def vocabulary(self, user_id, language, status, limit):
        self.calls.append(("vocabulary", user_id, language, status, limit))
        return {"language": "es", "counts": {"known": 2, "learning": 1, "due": 1},
                "words": [{"word": "el perro", "translation": "dog",
                           "status": "learning", "due": True}]}

    def recall_events(self, user_id, language):
        self.calls.append(("recall_events", user_id, language))
        return self.recalls

    def classify(self, user_id, language, tokens):
        self.calls.append(("classify", user_id, language, tokens))
        return {t: CLASSES[t] for t in tokens if t in CLASSES}

    def words(self, word_ids):
        return {w: {"id": w, "root": WORDS[w], "translation": f"t{w}"}
                for w in word_ids if w in WORDS}

    def insert_events(self, rows):
        self.events.extend(rows)
        return len(rows)

    def exposed(self, user_id, media, word_ids):
        return {e["word_id"] for e in self.events
                if e["user_id"] == user_id and e["kind"] == "exposure"
                and (e.get("context") or {}).get("media") == media and e["word_id"] in word_ids}

    # The user's list: word_id -> root. 7 and 8 are homographs.
    LIST = {2: "el perro", 4: "la", 7: "de", 8: "de", 10: "encontrar"}

    def user_words(self, user_id, language, roots):
        self.calls.append(("user_words", user_id, language, roots))
        return [{"word_id": w, "root": root} for w, root in self.LIST.items() if root in roots]

    # As find_roots and wordforms would resolve them; 11 isn't in the list.
    FORMS = {"encontré": 10, "El perro": 2, "hablé": 11, "comer": 3, "la": 4, "apagar": 12}

    def resolve_words(self, language, words):
        return {w: self.FORMS[w] for w in words if w in self.FORMS}

    def owned(self, user_id, word_ids):
        return {w for w in word_ids if w in self.LIST}

    def set_status(self, user_id, word_ids, status):
        self.calls.append(("set_status", user_id, word_ids, status))

    # Statuses of the list's words; 12 had its cards turned off in RemNote.
    STATUSES = {2: "learning", 4: "known", 7: "known", 8: "learning", 10: "learning",
                12: "disabled"}

    def statuses(self, user_id, word_ids):
        return {w: self.STATUSES[w] for w in word_ids if w in self.STATUSES}

    def add_words(self, user_id, word_ids, status):
        self.calls.append(("add_words", user_id, word_ids, status))

    def touch(self, user_id):
        self.calls.append(("touch", user_id))


def test_get_vocabulary_passes_the_user_and_parses_the_answer():
    store = FakeStore()
    vocab = vocabulary.get_vocabulary(store, USER, None, "due", 20)
    assert store.calls == [("vocabulary", USER, None, "due", 20), ("recall_events", USER, "es")]
    assert vocab.counts.due == 1
    assert vocab.words[0].word == "el perro"


def test_score_text_counts_running_words_and_skips_non_vocabulary():
    store = FakeStore()
    # "Trump" and "3" aren't vocabulary; "perro" appears twice.
    score = vocabulary.score_text(store, USER, "es",
                                  "El perro come la manzana. Trump, 3 casa; perro!")
    [(_, user, language, tokens)] = store.calls
    assert (user, language) == (USER, "es")
    assert tokens == sorted(set(tokens)) and "3" not in tokens
    assert score.running_words == 7
    assert (score.known_percent, score.learning_percent, score.new_percent) == (42.9, 28.6, 28.6)
    assert [(w.word, w.occurrences) for w in score.learning] == [("el perro", 2)]
    # An ignored word counts against comprehension but isn't suggested.
    assert [w.word for w in score.new] == ["la manzana"]


def test_score_text_without_vocabulary():
    score = vocabulary.score_text(FakeStore(), USER, "es", "Trump 2024")
    assert score.running_words == 0 and score.known_percent == 0.0


def test_words_split_on_apostrophes_and_digits():
    assert vocabulary._WORD.findall("l'homme 4K über-groß") == ["l", "homme", "K", "über", "groß"]


def test_record_exposure_logs_only_learning_words_once_each():
    store = FakeStore()
    # 'encontré' is a form of a learning word; 'la' is known; of the homographs
    # 'de', 7 is known and 8 learning; 'casa' isn't in the list.
    summary = vocabulary.record_exposure(store, USER, "es",
                                         ["el perro", "encontré", "la", "de", "casa", "el perro"])
    assert summary.recorded == 3
    assert [e["word_id"] for e in store.events] == [2, 8, 10]
    assert store.events[0] == {"user_id": USER, "word_id": 2, "kind": "exposure", "source": "chatgpt"}
    assert summary.not_learning == ["la", "casa"]


def test_record_exposure_with_no_learning_words_writes_nothing():
    store = FakeStore()
    summary = vocabulary.record_exposure(store, USER, "es", ["la", "apagar"])
    assert summary.recorded == 0 and store.events == []
    assert summary.not_learning == ["la", "apagar"]


def test_record_seen_logs_each_word_once_per_media():
    store = FakeStore()
    req = vocabulary.SeenRequest(source="video", media="youtube:abc", word_ids=[5, 2, 5])
    assert vocabulary.record_seen(store, USER, req).recorded == 2
    assert store.events == [
        {"user_id": USER, "word_id": w, "kind": "exposure", "source": "video",
         "context": {"media": "youtube:abc"}}
        for w in (2, 5)
    ]
    # Sent again (a retry, or the same line later in the video): nothing new.
    assert vocabulary.record_seen(store, USER, req).recorded == 0
    # Another video counts again.
    other = req.model_copy(update={"media": "youtube:xyz"})
    assert vocabulary.record_seen(store, USER, other).recorded == 2


def test_record_seen_drops_words_no_longer_in_the_dictionary():
    store = FakeStore()
    req = vocabulary.SeenRequest(source="reader", media="https://example.com/a", word_ids=[2, 999])
    assert vocabulary.record_seen(store, USER, req).recorded == 1
    assert [e["word_id"] for e in store.events] == [2]


def test_set_word_status_moves_every_listed_word_with_that_root():
    store = FakeStore()
    change = vocabulary.set_word_status(store, USER, "es",
                                        ["el perro", " de ", "de", "la casa"], "known")
    assert ("set_status", USER, [2, 7, 8], "known") in store.calls
    assert (change.changed, change.not_found) == (["el perro", "de"], ["la casa"])


def test_set_word_status_finds_forms_in_the_users_list():
    store = FakeStore()
    change = vocabulary.set_word_status(store, USER, "es",
                                        ["encontré", "El perro", "hablé"], "known")
    assert ("set_status", USER, [2, 10], "known") in store.calls
    assert (change.changed, change.not_found) == (["encontré", "El perro"], ["hablé"])


def test_set_word_status_with_nothing_found_updates_nothing():
    store = FakeStore()
    change = vocabulary.set_word_status(store, USER, "es", ["casa"], "learning")
    assert not any(c[0] == "set_status" for c in store.calls)
    assert change.not_found == ["casa"]


def test_add_words_as_learning_adds_new_words_and_leaves_listed_ones():
    store = FakeStore()
    added = vocabulary.add_words(store, USER, "es",
                                 ["comer", " hablé ", "la", "encontré", "apagar", "xyz"], "learning")
    assert store.calls == [("add_words", USER, [3, 11], "learning")]
    assert (added.added, added.already, added.not_found) == (
        ["comer", "hablé"], ["la", "encontré", "apagar"], ["xyz"])


def test_add_words_as_known_also_moves_learning_words_to_known():
    store = FakeStore()
    added = vocabulary.add_words(store, USER, "es", ["comer", "encontré", "la", "apagar"], "known")
    assert store.calls == [("add_words", USER, [3], "known"),
                           ("set_status", USER, [10], "known")]
    assert (added.added, added.already) == (["comer", "encontré"], ["la", "apagar"])


def test_add_words_already_known_changes_nothing():
    store = FakeStore()
    added = vocabulary.add_words(store, USER, "es", ["la", "casa"], "known")
    assert store.calls == []
    assert (added.added, added.already, added.not_found) == ([], ["la"], ["casa"])


def test_add_words_moving_only_learning_words_marks_the_list_changed():
    store = FakeStore()
    vocabulary.add_words(store, USER, "es", ["encontré"], "known")
    assert store.calls == [("set_status", USER, [10], "known"), ("touch", USER)]


def recall(word_id, root, kind, at, note=None):
    return {"word_id": word_id, "kind": kind, "occurred_at": at,
            "context": {"direction": "produce", **({"note": note} if note else {})},
            "words": {"root": root, "language": "es"}}


def test_get_vocabulary_lists_words_last_answered_wrong_newest_first():
    store = FakeStore(recalls=[  # newest first, as recall_events returns them
        recall(1, "el piso", "recall_wrong", "2026-10-30T10:00:00+00:00", "wrote apartamiento"),
        recall(3, "comer", "recall_correct", "2026-10-30T09:00:00+00:00"),
        recall(5, "la manzana", "recall_wrong", "2026-10-29T09:00:00+00:00"),
        recall(3, "comer", "recall_wrong", "2026-10-28T09:00:00+00:00", "comí for como"),
        recall(1, "el piso", "recall_correct", "2026-10-27T09:00:00+00:00"),
    ])
    mistakes = vocabulary.get_vocabulary(store, USER, None, "due", 20).mistakes
    assert [(m.word, m.date, m.note) for m in mistakes] == [
        ("el piso", "2026-10-30", "wrote apartamiento"), ("la manzana", "2026-10-29", None)]


class StuckStore(FakeStore):
    """The user's learning rows among the common words: 21 was reviewed long
    ago under the old schedule, 22 in RemNote, 23 and 24 never."""
    LEARNING = {
        21: ("ya", "already", "2025-06-01T10:00:00"),
        22: ("según", "according to", None),
        23: ("que", "that, which", None),
        24: ("quedar", "to stay", None),
    }

    def __init__(self, events=()):
        super().__init__()
        del self.events  # FakeStore's log of inserts; here events() reads
        self.logged = list(events)

    def learning_rows(self, user_id, word_ids):
        self.calls.append(("learning_rows", user_id, word_ids))
        return [{"word_id": w, "last_reviewed_at": at, "words": {"root": root, "translation": t}}
                for w, (root, t, at) in self.LEARNING.items() if w in word_ids]

    def reviewed(self, user_id, word_ids):
        self.calls.append(("reviewed", user_id, word_ids))
        return {22} & set(word_ids)

    def events(self, user_id, word_ids, kinds):
        return [e for e in self.logged if e["word_id"] in word_ids and e["kind"] in kinds]


def seen(word_id, media, source="video", kind="exposure"):
    return {"word_id": word_id, "kind": kind, "source": source,
            "context": {"media": media} if media else None}


def test_stuck_words_are_learning_never_reviewed_and_most_common_first():
    store = StuckStore()
    stuck = vocabulary.stuck_words(store, USER, [24, 23, 22, 21, 99])
    assert [(w.word_id, w.word, w.translation) for w in stuck.words] == [
        (24, "quedar", "to stay"), (23, "que", "that, which")]
    assert ("reviewed", USER, [22, 23, 24]) in store.calls


def test_stuck_words_count_distinct_videos_and_lookups():
    store = StuckStore(events=[
        seen(23, "youtube:a"), seen(23, "youtube:a"), seen(23, "youtube:b"),
        seen(23, "https://example.com/page", source="reader"),
        seen(24, "youtube:a"), seen(24, None, kind="lookup"), seen(24, None, kind="lookup"),
    ])
    stuck = {w.word: (w.videos, w.lookups) for w in vocabulary.stuck_words(store, USER, [23, 24]).words}
    assert stuck == {"que": (2, 0), "quedar": (1, 2)}


def test_stuck_words_with_none_learning_reads_nothing_else():
    store = StuckStore()
    assert vocabulary.stuck_words(store, USER, [1, 2]).words == []
    assert [c[0] for c in store.calls] == ["learning_rows"]


def test_move_words_moves_only_words_in_the_users_list():
    store = FakeStore()
    moved = vocabulary.move_words(store, USER, [10, 2, 2, 11], "known")
    assert store.calls == [("set_status", USER, [2, 10], "known")]
    assert moved.moved == [2, 10]


def test_move_words_with_none_in_the_list_updates_nothing():
    store = FakeStore()
    assert vocabulary.move_words(store, USER, [11], "known").moved == []
    assert store.calls == []
