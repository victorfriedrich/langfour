"""word_importance: rank a text's words once with Jev, save them, mark the key words."""
import asyncio
import os

os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

import pytest

import word_importance
from word_importance import (
    KEY_FROM,
    MAX_KEY_WORDS,
    MIN_KEY_WORDS,
    RUBRIC_VERSION,
    media_ranks,
    rank,
    tokens_of_chunks,
    with_importance,
)

CHUNKS = [{"text": "El equipo gana.", "words": [[0, 2, 1], [3, 9, 2], [10, 14, 3]]},
          {"text": "Los equipos, ah.", "words": [[0, 3, 1], [4, 11, 2], [13, 15, 4]]}]
ROOTS = {1: "el", 2: "el equipo", 3: "ganar", 4: "ah"}


class Store:
    def __init__(self, row):
        self.row = row
        self.saved = []

    def get(self, user_id, language, media_id, columns):
        return {c: self.row.get(c) for c in columns.split(",")} if self.row else None

    def save_word_ranks(self, user_id, language, media_id, ranks, version):
        self.saved.append((user_id, language, media_id, ranks, version))
        self.row.update(word_ranks=ranks, word_ranks_version=version)


@pytest.fixture
def jev(monkeypatch):
    """Jev answering 8 for `here` and 6 for `general`, recording each batch."""
    batches = []

    async def ask(client, state, asked):
        batches.append((state, asked))
        return {key[1:]: [8.0, 6.0] for key in asked if key.startswith("h")}

    monkeypatch.setattr(word_importance, "ask", ask)
    monkeypatch.setattr(word_importance, "roots_of", lambda sb, language, ids: {i: ROOTS[i] for i in ids if i != 4})
    return batches


def test_all_the_words_go_in_one_request_with_the_text_once(jev):
    ranks = asyncio.run(rank(None, "es", "series", "Ep 1", "El equipo gana.\nLos equipos, ah.",
                             tokens_of_chunks(CHUNKS)))
    assert ranks == {"1": [8.0, 6.0], "2": [8.0, 6.0], "3": [8.0, 6.0]}  # 4 is invalid
    (state, asked), = jev
    assert state["text"] == "El equipo gana.\nLos equipos, ah."
    assert state["kind"] == "TV episode" and state["language"] == "Spanish"
    assert state["words"]["w2"] == {"word": "el equipo", "forms": ["equipo", "equipos"], "count": 2}
    assert set(asked) == {"h1", "g1", "h2", "g2", "h3", "g3"}
    # The questions point at the state instead of repeating it.
    assert asked["h2"]["instructions"] == "Apply rubric.here to words.w2."


def test_a_request_jev_finds_too_long_is_split_in_two(monkeypatch):
    sent = []

    async def ask(client, state, asked):
        sent.append(sorted(state["words"]))
        if len(state["words"]) > 2:
            raise word_importance.TooLong
        return {key[1:]: [4.0, 3.0] for key in asked if key.startswith("h")}

    monkeypatch.setattr(word_importance, "ask", ask)
    monkeypatch.setattr(word_importance, "roots_of", lambda sb, language, ids: {i: ROOTS[i] for i in ids})
    ranks = asyncio.run(rank(None, "es", "song", "", "text", tokens_of_chunks(CHUNKS)))
    assert set(ranks) == {"1", "2", "3", "4"}
    assert sent == [["w1", "w2", "w3", "w4"], ["w1", "w2"], ["w3", "w4"]]


def test_a_text_without_known_words_asks_nothing(jev, monkeypatch):
    monkeypatch.setattr(word_importance, "roots_of", lambda sb, language, ids: {})
    assert asyncio.run(rank(None, "es", "song", "", "text", tokens_of_chunks(CHUNKS))) == {}
    assert jev == []


def test_a_library_item_is_ranked_once_then_read_back(jev):
    store = Store({"kind": "song", "title": "Canción", "chunks": CHUNKS})
    first = asyncio.run(media_ranks(None, store, "alice", "cancion", "es", None))
    again = asyncio.run(media_ranks(None, store, "alice", "cancion", "es", None))
    assert first == again == {"1": [8.0, 6.0], "2": [8.0, 6.0], "3": [8.0, 6.0]}
    assert len(jev) == 1
    assert store.saved == [("alice", "es", "cancion", first, RUBRIC_VERSION)]


def test_ranks_from_an_older_rubric_are_redone(jev):
    store = Store({"kind": "song", "title": "", "chunks": CHUNKS,
                   "word_ranks": {"1": [1, 1]}, "word_ranks_version": RUBRIC_VERSION - 1})
    assert asyncio.run(media_ranks(None, store, "alice", "x", "es", None))["1"] == [8.0, 6.0]


def test_items_without_word_spans_are_read_with_the_tokenizer(jev):
    store = Store({"kind": "text", "title": "", "chunks": [{"text": "El equipo"}]})
    tokens = [{"content": "El", "id": 1}, {"content": " "}, {"content": "equipo", "id": 2}]
    ranks = asyncio.run(media_ranks(None, store, "alice", "x", "es", lambda text, language: tokens))
    assert set(ranks) == {"1", "2"}


def test_a_failed_ranking_leaves_the_list_unranked_and_saves_nothing(monkeypatch):
    async def down(*args):
        raise RuntimeError("Jev HTTP 502")

    monkeypatch.setattr(word_importance, "rank", down)
    store = Store({"kind": "song", "title": "", "chunks": CHUNKS})
    assert asyncio.run(media_ranks(None, store, "alice", "x", "es", None)) is None
    assert store.saved == []


def key_words(scores, **fields):
    missing = [{"id": i, "content": f"w{i}", **fields} for i in range(len(scores))]
    ranks = {str(i): [score, score] for i, score in enumerate(scores) if score is not None}
    return [w["id"] for w in with_importance(missing, ranks) if w["key"]]


def test_at_most_the_maximum_are_key_words_and_the_most_important_win():
    scores = [KEY_FROM + i / 100 for i in range(MAX_KEY_WORDS + 3)]
    assert key_words(scores) == list(range(3, MAX_KEY_WORDS + 3))


def test_the_minimum_are_key_words_however_low_they_score():
    assert key_words([KEY_FROM - 1 - i / 100 for i in range(MIN_KEY_WORDS + 3)]) == list(range(MIN_KEY_WORDS))


def test_between_the_minimum_and_the_maximum_the_limit_decides():
    above = MIN_KEY_WORDS + 2
    scores = [KEY_FROM + 1] * above + [KEY_FROM - 1] * 3
    assert key_words(scores) == list(range(above))


def test_a_short_list_has_only_the_words_it_has():
    assert key_words([1.0, 1.0]) == [0, 1]


def test_unranked_flagged_and_invalid_words_are_never_key():
    assert key_words([None, None]) == []
    assert key_words([5.0, 5.0], status="flagged") == []
    assert key_words([5.0, 5.0], status="invalid") == []


def test_unranked_words_come_back_as_they_were():
    assert with_importance([{"id": 1, "content": "w"}], None) == [
        {"id": 1, "content": "w", "importance": None, "key": False}]
