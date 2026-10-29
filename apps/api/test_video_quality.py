"""Jev answer handling and the hide rules in video_quality.py."""

from unittest.mock import Mock

import httpx
import pytest

import video_quality as vq


def answers(integrity=None, lesson=0.0, sung=0.0, content=7, developed=6, transferable=7,
            grammar="B1"):
    def scale(value):
        return {"probabilities": {str(k): (1.0 if k == value else 0.0) for k in range(1, 11)}}

    def yes(p):
        return {"probabilities": {"yes": p, "no": 1 - p}}

    return {
        "integrity": {"probabilities": integrity or {"clean": 0.8, "patchy": 0.2, "garbled": 0.0}},
        "foreign_lesson": yes(lesson),
        "sung": yes(sung),
        "grammar": {"probabilities": {k: (1.0 if k == grammar else 0.0) for k in vq.GRAMMAR_SCORES}},
        "content": scale(content),
        "developed": scale(developed),
        "transferable": scale(transferable),
    }


def test_row_maps_probabilities_to_scores():
    r = vq.row("v", "es", answers(grammar="B2", content=8, transferable=6))
    assert r["integrity"] == "clean" and r["p_garbled"] == 0.0
    assert (r["grammar"], r["content"], r["transferable"]) == (7, 8, 6)
    assert r["rubric_version"] == vq.RUBRIC_VERSION
    assert set(r["jev"]) == set(vq.QUESTIONS)


@pytest.mark.parametrize(("kwargs", "reason"), [
    ({}, None),
    ({"integrity": {"clean": 0.1, "patchy": 0.3, "garbled": 0.6}}, "garbled"),
    ({"integrity": {"clean": 0.2, "patchy": 0.3, "garbled": 0.5}}, None),   # unsure: keep
    ({"lesson": 0.95}, "foreign_lesson"),
    ({"lesson": 0.74}, None),
    ({"sung": 0.99}, "sung"),
    ({"sung": 0.6}, None),
    ({"content": 4, "transferable": 5}, "low_quality"),
    ({"content": 4, "transferable": 6}, None),                              # mean is 5
    ({"developed": 1}, None),                                               # D is not a filter
])
def test_hidden(kwargs, reason):
    assert vq.hidden(vq.row("v", "es", answers(**kwargs))) == reason


def test_short_transcripts_go_whole_and_long_ones_in_three_windows():
    assert vq.excerpts(["a"] * 10) == [" ".join(["a"] * 10)]
    long = [str(i) for i in range(10_000)]
    parts = vq.excerpts(long)
    assert len(parts) == 3 and all(len(p.split()) == vq.EXCERPT_WORDS for p in parts)
    assert parts[1].split()[0] == "4500"


def test_ask_retries_when_jev_leaves_a_question_out(monkeypatch):
    monkeypatch.setattr(vq.time, "sleep", lambda _s: None)
    partial = {k: v for k, v in answers().items() if k != "sung"}
    http = Mock()
    http.post.side_effect = [httpx.Response(200, json={"answers": partial}),
                             httpx.Response(200, json={"answers": answers()})]
    assert set(vq.ask(http, "t", ["hola"])) == set(vq.QUESTIONS)
    assert http.post.call_count == 2


def test_ask_gives_up_on_a_client_error(monkeypatch):
    monkeypatch.setattr(vq.time, "sleep", lambda _s: None)
    http = Mock()
    http.post.return_value = httpx.Response(401, text="no key")
    with pytest.raises(RuntimeError, match="401"):
        vq.ask(http, "t", ["hola"])
    assert http.post.call_count == 1


def test_other_languages_are_not_scored():
    sb, http = Mock(), Mock()
    assert vq.score_and_store(sb, http, "v", "de", "t", ["hallo"]) is None
    http.post.assert_not_called() and sb.table.assert_not_called()


def test_hidden_ids_pages_through_the_table():
    rows = [{"video_id": f"v{i}", "p_garbled": 0.9 if i % 2 else 0.0, "p_foreign_lesson": 0.0,
             "p_sung": 0.0, "content": 7, "transferable": 7} for i in range(1500)]
    pages = [rows[:1000], rows[1000:]]
    query = Mock()
    query.select.return_value = query.order.return_value = query.eq.return_value = query
    query.range.return_value.execute.side_effect = [Mock(data=p) for p in pages]
    sb = Mock()
    sb.table.return_value = query
    assert vq.hidden_ids(sb) == {f"v{i}" for i in range(1500) if i % 2}
