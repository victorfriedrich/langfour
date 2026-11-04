"""word_familiarity: three groups of a text's new words, rated per learner."""
import asyncio
import os

os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

import pytest

import word_familiarity
import word_importance
from word_familiarity import AddBucketWords, BucketMove, add_words, panel_words, with_buckets


def word(i, status="valid"):
    return {"id": i, "content": f"w{i}", "translation": None, "status": status}


def test_links_decide_the_first_group_and_importance_the_other_two():
    missing = [word(i) for i in range(1, 24)]
    ranks = {str(i): [5.0 - i / 10, 5.0 - i / 10] for i in range(1, 24)}
    out = {w["id"]: w for w in with_buckets(missing, ranks, {1: 4.8, 2: 4.0, 3: 3.99})}
    assert out[1]["bucket"] == "probably" and out[2]["bucket"] == "probably"
    assert out[1]["key"] is False
    # The key words come from what is left, most important first, at most 15.
    should = [i for i, w in out.items() if w["bucket"] == "should"]
    assert should == list(range(3, 18))
    assert out[18]["bucket"] == "skip"
    assert out[23]["familiarity"] is None


def test_a_flagged_word_is_never_assumed_known():
    out = with_buckets([word(1, "flagged")], None, {1: 5.0})
    assert out[0]["bucket"] == "skip"


def test_unranked_words_wait_in_the_last_group():
    out = with_buckets([word(1), word(2)], None, {})
    assert [w["bucket"] for w in out] == ["skip", "skip"]


def test_an_account_without_languages_keeps_the_old_list(monkeypatch):
    monkeypatch.setattr(word_familiarity, "known_languages", lambda sb, user: None)
    out = asyncio.run(panel_words(None, "u", "es", [word(1)], None))
    assert out["buckets"] is False and "bucket" not in out["missing_words"][0]


def test_a_failure_only_costs_the_groups(monkeypatch):
    def broken(sb, user):
        raise RuntimeError("no column")
    monkeypatch.setattr(word_familiarity, "known_languages", broken)
    out = asyncio.run(panel_words(None, "u", "es", [word(1)], None))
    assert out["buckets"] is False and out["missing_words"][0]["id"] == 1


def test_only_unrated_words_are_rated_and_the_list_does_not_wait(monkeypatch):
    rated = []

    async def rate(sb, user, language, languages, ids):
        rated.append((user, language, languages, ids))

    monkeypatch.setattr(word_familiarity, "known_languages", lambda sb, user: ["English", "French"])
    monkeypatch.setattr(word_familiarity, "saved_scores", lambda sb, user, ids: {1: 4.5})
    monkeypatch.setattr(word_familiarity, "rate", rate)

    async def run():
        first = await panel_words(None, "u", "es", [word(1), word(2)], None)
        await asyncio.gather(*word_importance._running.values())
        return first

    out = asyncio.run(run())
    assert out["buckets"] is True and out["ranking"] is True
    assert {w["id"]: w["bucket"] for w in out["missing_words"]} == {1: "probably", 2: "skip"}
    assert rated == [("u", "es", ["English", "French"], [2])]


def test_invalid_words_are_not_rated_and_do_not_keep_the_panel_asking(monkeypatch):
    async def rate(*_):
        raise AssertionError("nothing to rate")

    monkeypatch.setattr(word_familiarity, "known_languages", lambda sb, user: ["English"])
    monkeypatch.setattr(word_familiarity, "saved_scores", lambda sb, user, ids: {1: 3.0})
    monkeypatch.setattr(word_familiarity, "rate", rate)
    out = asyncio.run(panel_words(None, "u", "es", [word(1), word(2, "invalid")], None))
    assert out["ranking"] is False


def test_a_request_refused_as_too_long_is_split(monkeypatch):
    sizes = []

    async def ask(client, state, ids):
        sizes.append(len(ids))
        if len(ids) > 2:
            raise word_familiarity.TooLong
        return dict.fromkeys(ids, 4.0)

    monkeypatch.setattr(word_familiarity, "ask", ask)
    entries = {i: {"word": str(i), "translation": None} for i in range(4)}
    scores = asyncio.run(word_familiarity._ask_all(None, {}, entries))
    assert sorted(scores) == [0, 1, 2, 3] and sizes == [4, 2, 2]


class Query:
    def __init__(self, sb, table):
        self.sb, self.table_name = sb, table

    def insert(self, rows):
        if self.sb.fail_events:
            raise RuntimeError("log down")
        self.sb.events.extend(rows)
        return self

    def execute(self):
        return type("R", (), {"data": self.sb.added})


class Store:
    def __init__(self, fail_events=False):
        self.calls, self.events, self.added, self.fail_events = [], [], 3, fail_events

    def rpc(self, name, params):
        self.calls.append((name, params))
        return Query(self, name)

    def table(self, name):
        return Query(self, name)


PAYLOAD = AddBucketWords(familiar=[1, 2], priority=[3], source="vid",
                         moves=[BucketMove(word_id=2, was="should", now="probably")])


def test_adding_saves_both_groups_and_logs_what_moved():
    sb = Store()
    assert add_words(sb, "u", PAYLOAD) == 3
    assert sb.calls == [("add_bucket_words", {"p_user_id": "u", "p_familiar": [1, 2],
                                              "p_priority": [3], "p_source": "vid"})]
    assert sb.events == [{"user_id": "u", "word_id": 2, "kind": "bucket_move", "source": "web",
                          "context": {"from": "should", "to": "probably", "text": "vid"}}]


def test_a_failed_log_does_not_fail_the_add():
    assert add_words(Store(fail_events=True), "u", PAYLOAD) == 3


def test_a_move_names_real_groups():
    with pytest.raises(ValueError):
        BucketMove(word_id=1, was="should", now="elsewhere")
