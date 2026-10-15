"""Candidate lookup and Jev outcome rules for unknown tokens."""

from unittest.mock import Mock

import pytest


@pytest.fixture
def wm(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.signature")
    monkeypatch.setenv("REQUIRE_SERVICE_ROLE", "0")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    import database
    import word_matching
    monkeypatch.setitem(database.word_cache, "es", {
        "words": {"follar": 1, "la bellota": 2, "editar": 3, "el edificio": 4},
        "wordforms": {"follamos": 1, "bellotas": 2, "editaste": 3, "edificios": 4},
    })
    return word_matching


def test_candidates_share_the_longest_prefix_first_and_ignore_accents(wm):
    index = wm.CandidateIndex("es")
    assert index.candidates("editaron")[0] == 3
    assert index.candidates("fóllame") == [1]
    assert index.candidates("bellotitas") == [2]
    assert index.candidates("xyz") == []


def answers(probs, real):
    return {"root": {"probabilities": probs}, "real": {"noul": real}}


@pytest.mark.parametrize("probs, real, outcome, root_id", [
    ({"r0": 0.9, "r1": 0.05, "none": 0.05}, 0.8, "attach", 3),
    ({"r0": 0.9, "r1": 0.05, "none": 0.05}, 0.3, "pending", None),   # junk that picked a root
    ({"r0": 0.3, "r1": 0.1, "none": 0.6}, 0.9, "pending", None),     # real, no root: never a new root
    ({"r0": 0.9, "r1": 0.05, "none": 0.05}, 0.05, "not_a_word", None),
])
def test_match_outcomes(wm, monkeypatch, probs, real, outcome, root_id):
    monkeypatch.setattr(wm, "ask_jev", Mock(return_value=answers(probs, real)))
    m = wm.match(None, wm.CandidateIndex("es"), "editaron", "es")
    assert (m.outcome, m.root_id) == (outcome, root_id)
