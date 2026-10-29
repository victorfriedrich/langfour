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
    def __init__(self):
        self.calls = []
        self.events = []

    def vocabulary(self, user_id, language, status, limit):
        self.calls.append(("vocabulary", user_id, language, status, limit))
        return {"language": "es", "counts": {"known": 2, "learning": 1, "due": 1},
                "words": [{"word": "el perro", "translation": "dog",
                           "status": "learning", "due": True}]}

    def classify(self, user_id, language, tokens):
        self.calls.append(("classify", user_id, language, tokens))
        return {t: CLASSES[t] for t in tokens if t in CLASSES}

    def words(self, word_ids):
        return {w: {"id": w, "root": WORDS[w], "translation": f"t{w}"} for w in word_ids}

    def insert_events(self, rows):
        self.events.extend(rows)
        return len(rows)

    # The user's list: word_id -> root. 7 and 8 are homographs.
    LIST = {2: "el perro", 4: "la", 7: "de", 8: "de", 10: "encontrar"}

    def user_words(self, user_id, language, roots):
        self.calls.append(("user_words", user_id, language, roots))
        return [{"word_id": w, "root": root} for w, root in self.LIST.items() if root in roots]

    # As find_roots and wordforms would resolve them; 11 isn't in the list.
    FORMS = {"encontré": 10, "El perro": 2, "hablé": 11}

    def resolve_words(self, language, words):
        return {w: self.FORMS[w] for w in words if w in self.FORMS}

    def owned(self, user_id, word_ids):
        return {w for w in word_ids if w in self.LIST}

    def set_status(self, user_id, word_ids, status):
        self.calls.append(("set_status", user_id, word_ids, status))


def test_get_vocabulary_passes_the_user_and_parses_the_answer():
    store = FakeStore()
    vocab = vocabulary.get_vocabulary(store, USER, None, "due", 20)
    assert store.calls == [("vocabulary", USER, None, "due", 20)]
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


def test_record_exposure_logs_learning_and_new_words_once_each():
    store = FakeStore()
    summary = vocabulary.record_exposure(store, USER, "es",
                                         "El perro come la manzana, casa, perro.")
    assert summary.recorded == 2
    assert store.events == [
        {"user_id": USER, "word_id": 2, "kind": "exposure", "source": "chatgpt"},
        {"user_id": USER, "word_id": 5, "kind": "exposure", "source": "chatgpt"},
    ]


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
