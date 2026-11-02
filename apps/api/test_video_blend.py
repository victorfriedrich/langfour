"""The recommendation order in video_blend.py."""
import video_blend
from video_blend import rank, rejected


def look(interest=6, trash=3, sensitive="none", channel=None):
    return {"look": {"interest": interest, "trash": trash, "sensitive": sensitive, "channel": channel}}


def candidates(n):
    """n videos, most understood first."""
    return [(f"v{i}", 1 - i / 1000) for i in range(n)]


def test_rejections():
    assert rejected(None) is None
    assert rejected(look()["look"]) is None
    assert rejected(look(trash=7)["look"]) == "trash"
    assert rejected(look(trash=6)["look"]) is None
    assert rejected(look(interest=2)["look"]) == "dull"
    assert rejected(look(interest=3)["look"]) is None
    assert rejected(look(sensitive="strong")["look"]) == "sensitive"
    assert rejected(look(sensitive="mild")["look"]) is None


def test_no_signals_keep_known_words_order():
    assert rank(candidates(20), {}) == [f"v{i}" for i in range(20)]


def test_only_the_top_share_is_reordered():
    signals = {f"v{i}": look(interest=3) for i in range(20)}
    signals["v2"] = look(interest=9, trash=1)  # in the pool
    signals["v15"] = look(interest=10, trash=1)  # outside it
    order = rank(candidates(20), signals)
    assert order.index("v2") < order.index("v1")
    assert order[4:] == [f"v{i}" for i in range(4, 20)]


def test_understanding_still_counts():
    signals = {"v0": {**look(), "grammar": 5.0, "text": 7.0}, "v9": {**look(), "grammar": 5.0, "text": 7.0}}
    assert rank(candidates(10), signals)[0] == "v0"


def test_easier_grammar_beats_a_slightly_better_known_share():
    signals = {f"v{i}": {**look(), "grammar": 7.0, "text": 7.0} for i in range(10)}
    signals["v5"] = {**look(), "grammar": 4.0, "text": 7.0}
    order = rank(candidates(50), signals)
    assert order.index("v5") < order.index("v4")


def test_rejected_videos_are_gone_everywhere_even_outside_the_pool():
    signals = {"v0": look(trash=9), "v15": look(interest=1)}
    order = rank(candidates(20), signals)
    assert "v0" not in order and "v15" not in order
    assert len(order) == 18


def test_channel_limit_moves_the_third_video_to_the_end():
    signals = {f"v{i}": look(channel="same") for i in range(3)}
    order = rank(candidates(20), signals)
    assert order[-1] == "v2"
    assert len(order) == 20
    assert video_blend.PER_CHANNEL == 2


def test_a_video_without_a_channel_has_no_limit():
    signals = {f"v{i}": look(channel=None) for i in range(5)}
    assert rank(candidates(5), signals) == [f"v{i}" for i in range(5)]


def test_in_list_narrows_after_the_pool_and_small_lists_still_fill():
    order = rank(candidates(20), {}, in_list=lambda vid: vid in ("v1", "v19"))
    assert order == ["v1", "v19"]


def test_empty_candidates():
    assert rank([], {}) == []


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_a):
        return self

    def eq(self, column, value):
        return _Query([r for r in self.rows if r[column] == value])

    def order(self, *_a):
        return self

    def range(self, start, end):
        return _Query(self.rows[start:end + 1])

    def execute(self):
        return type("R", (), {"data": self.rows})


class _Db:
    def __init__(self, **tables):
        self.tables = tables

    def table(self, name):
        return _Query(self.tables[name])


def test_load_signals_covers_only_languages_with_verdicts():
    db = _Db(video_looks=[{"video_id": "a", "language": "es", "channel": "c", "interest": 7, "trash": 2, "sensitive": "none"}],
             video_scores=[
                 {"video_id": "a", "language": "es", "grammar": 5.0, "content": 6.0, "developed": 7.0, "transferable": 8.0},
                 {"video_id": "b", "language": "es", "grammar": 4.0, "content": 3.0, "developed": 3.0, "transferable": 3.0},
                 {"video_id": "z", "language": "de", "grammar": 4.0, "content": 3.0, "developed": 3.0, "transferable": 3.0},
             ])
    signals = video_blend.load_signals(db)
    assert set(signals) == {"es"}
    assert signals["es"]["a"]["look"]["interest"] == 7
    assert signals["es"]["a"]["text"] == 7.0
    assert signals["es"]["b"] == {"grammar": 4.0, "text": 3.0}


def test_load_signals_with_no_verdicts_is_empty():
    assert video_blend.load_signals(_Db(video_looks=[], video_scores=[])) == {}
