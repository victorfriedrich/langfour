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
