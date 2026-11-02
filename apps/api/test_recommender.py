import asyncio
import builtins
import json

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from recommender import Recommender


def blank_recommender(base_folder=None):
    recommender = Recommender.__new__(Recommender)
    recommender.base_folder = base_folder
    recommender.languages = ["es"]
    recommender.blacklisted_files = set()
    recommender.documents = {}
    recommender.filenames = {}
    recommender.categories = {}
    recommender.titles = {}
    recommender.max_word_ids = {}
    recommender.matrices = {}
    recommender.presence = {}
    recommender.total_words_per_doc = {}
    recommender.distinct_words_per_doc = {}
    return recommender


def make_recommender(rows, categories=None, titles=None):
    """Rows are times each word is spoken in a video."""
    recommender = blank_recommender()
    matrix = csr_matrix(np.asarray(rows, dtype=np.int16))
    recommender._index_matrix("es", matrix)
    recommender.filenames = {
        "es": [f"video-{index}_processed.json" for index in range(matrix.shape[0])]
    }
    recommender.categories = {
        "es": categories or ["Other"] * matrix.shape[0]
    }
    recommender.titles = {
        "es": titles or [f"Video {index}" for index in range(matrix.shape[0])]
    }
    recommender.max_word_ids = {"es": max(matrix.shape[1] - 1, 0)}
    recommender.hidden_videos = set()
    return recommender


def test_hidden_videos_are_never_recommended():
    recommender = make_recommender([np.ones(150, dtype=np.int8)] * 3)
    recommender.hidden_videos = {"video-1"}

    async def get_known_words(_user_id):
        return [0]

    async def get_watched_videos(_user_id):
        return []

    recommender.get_known_words = get_known_words
    recommender.get_watched_videos = get_watched_videos

    by_words = [v["id"] for v in recommender.recommend_videos_by_words([0], "es")]
    for_user = [v["id"] for v in asyncio.run(recommender.recommend_videos("user", "es"))]
    assert sorted(by_words) == sorted(for_user) == ["video-0", "video-2"]


def test_unreadable_scores_hide_nothing(monkeypatch):
    import video_quality

    def boom(_sb):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(video_quality, "hidden_ids", boom)
    recommender = Recommender.__new__(Recommender)
    recommender.supabase = None
    assert recommender._load_hidden_videos() == set()


def test_categories_come_from_loaded_manifest_data():
    recommender = make_recommender(
        [[1], [1], [1], [0]],
        ["Travel", "Cooking", "Travel", "Unknown"],
    )

    assert recommender.get_categories("es") == [
        {"category": "Cooking", "icon": None},
        {"category": "Travel", "icon": None},
    ]



def test_video_count_matches_word_share_denominator():
    recommender = make_recommender(
        [[1, 1], [1, 0], [0, 1]],
        ["Travel", "Travel", "Cooking"],
    )

    assert recommender.count_documents("es", "Travel") == 2
    assert recommender.count_documents("es") == 3
    recs = recommender.recommend_words_to_learn("es", [], filter_category="Travel")
    assert {r["word_id"]: (r["frequency"], r["improvement"]) for r in recs} == {
        0: (2, 1.0),
        1: (1, 0.5),
    }


def test_word_recommendations_rank_by_videos_then_word_id():
    recommender = make_recommender(
        [[0, 1, 1, 1], [0, 1, 0, 1], [1, 0, 0, 1]],
    )

    recs = recommender.recommend_words_to_learn("es", [])
    assert [r["word_id"] for r in recs] == [3, 1, 0, 2]

def test_vocabulary_coverage_is_numeric_only(monkeypatch):
    recommender = make_recommender([
        [1, 1, 0, 0],  # 50% understood
        [1, 0, 0, 0],  # 100% understood
        [0, 0, 1, 1],  # 0% understood
        [0, 0, 0, 0],  # non-video cache artifact; excluded
    ])

    def fail_if_opened(*args, **kwargs):
        raise AssertionError("coverage must not open transcript files")

    monkeypatch.setattr(builtins, "open", fail_if_opened)

    assert recommender.calculate_vocabulary_coverage([0], "es") == {
        "top30_avg": pytest.approx(100.0),
        "bottom30_avg": pytest.approx(0.0),
    }


def test_vocabulary_coverage_uses_non_overflowing_accumulation():
    recommender = make_recommender([np.ones(200, dtype=np.int8)])

    assert recommender.calculate_vocabulary_coverage(list(range(200)), "es") == {
        "top30_avg": pytest.approx(100.0),
        "bottom30_avg": pytest.approx(100.0),
    }


def test_vocabulary_coverage_handles_no_documents():
    recommender = make_recommender(np.empty((0, 4), dtype=np.int8))

    assert recommender.calculate_vocabulary_coverage([0], "es") == {
        "top30_avg": 0.0,
        "bottom30_avg": 0.0,
    }


def test_recommendations_use_manifest_titles_without_opening_transcripts(monkeypatch):
    recommender = make_recommender(
        [np.ones(150, dtype=np.int8)],
        titles=["Compact metadata title"],
    )

    async def get_known_words(_user_id):
        return [0]

    async def get_watched_videos(_user_id):
        return []

    recommender.get_known_words = get_known_words
    recommender.get_watched_videos = get_watched_videos

    def fail_if_opened(*args, **kwargs):
        raise AssertionError("recommendations must not open transcript files")

    monkeypatch.setattr(builtins, "open", fail_if_opened)

    assert recommender.recommend_videos_by_words([0], "es", top_n=1)[0]["title"] == (
        "Compact metadata title"
    )
    assert asyncio.run(recommender.recommend_videos("user", "es", top_n=1))[0]["title"] == (
        "Compact metadata title"
    )


def test_matrix_manifest_persists_titles_and_loads_without_transcripts(tmp_path):
    language_dir = tmp_path / "es"
    language_dir.mkdir()
    transcript = {
        "category": "Travel",
        "content": [{"id": 4}, {"id": 9}],
        "title": "A trip",
    }
    transcript_path = language_dir / "abc_processed.json"
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")

    recommender = blank_recommender(str(tmp_path))
    recommender._ensure_language_loaded("es")

    manifest_path = language_dir / "document_term_counts.npz.meta.json"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["titles"] == ["A trip"]

    transcript_path.write_text("not valid JSON", encoding="utf-8")
    loaded = blank_recommender(str(tmp_path))

    assert loaded._try_load_cached_language("es") is True
    assert loaded.titles["es"] == ["A trip"]


def test_coverage_counts_every_word_and_new_words_are_distinct():
    # Word 0 is said 50 times among 150 different words, 199 words heard in
    # all: knowing it covers a quarter of the speech, one word of the 150.
    recommender = make_recommender([[50] + [1] * 149])

    [video] = recommender.recommend_videos_by_words([0], "es")
    assert video["percentUnderstood"] == pytest.approx(50 / 199 * 100, abs=0.01)
    assert video["newWords"] == 149 and video["knownWords"] == 1

    ratios, new, known = recommender._score_documents_by_words([1, 2], "es")
    assert ratios[0] == pytest.approx(2 / 199) and new[0] == 148 and known[0] == 2


def test_words_to_learn_rank_by_videos_not_repeats():
    # Word 0 is said 50 times in one video; word 1 once in each of two.
    recommender = make_recommender([[50, 1], [0, 1]])

    recs = recommender.recommend_words_to_learn("es", [])
    assert [(r["word_id"], r["frequency"]) for r in recs] == [(1, 2), (0, 1)]


def test_too_short_videos_are_judged_on_distinct_words():
    # 300 words spoken, but only 50 different ones: still too short to recommend.
    recommender = make_recommender([[6] * 50 + [0] * 100, [1] * 150])

    async def none(_user_id):
        return []

    recommender.get_known_words = none
    recommender.get_watched_videos = none
    assert [v["id"] for v in asyncio.run(recommender.recommend_videos("user", "es"))] == ["video-1"]


def test_a_binary_cache_is_left_alone_and_counts_are_built(tmp_path):
    from scipy.sparse import save_npz
    language_dir = tmp_path / "es"
    language_dir.mkdir()
    (language_dir / "abc_processed.json").write_text(json.dumps({
        "category": "Travel", "title": "A trip",
        "content": [{"id": 4}, {"content": " "}, {"id": 4}, {"id": 9}],
    }), encoding="utf-8")
    # The cache from before counts: ones, under the old name, which older
    # code (a rollback) keeps reading.
    old_matrix = language_dir / "document_term_matrix.npz"
    save_npz(old_matrix, csr_matrix(np.asarray([[0, 0, 0, 0, 1, 0, 0, 0, 0, 1]], dtype=np.int8)))
    old_meta = json.dumps({"filenames": ["abc_processed.json"], "categories": ["Travel"],
                           "titles": ["A trip"], "max_word_id": 9})
    (language_dir / "document_term_matrix.npz.meta.json").write_text(old_meta, encoding="utf-8")

    recommender = blank_recommender(str(tmp_path))
    assert recommender._try_load_cached_language("es") is False
    recommender._ensure_language_loaded("es")

    assert recommender.matrices["es"].toarray()[0, [4, 9]].tolist() == [2, 1]
    assert recommender.total_words_per_doc["es"].tolist() == [3]
    assert recommender.distinct_words_per_doc["es"].tolist() == [2]
    meta = json.loads((language_dir / "document_term_counts.npz.meta.json").read_text())
    assert meta["weights"] == "counts"
    assert (language_dir / "document_term_matrix.npz.meta.json").read_text() == old_meta
    assert blank_recommender(str(tmp_path))._try_load_cached_language("es") is True

    # A counts-named cache without the marker is not trusted either.
    meta.pop("weights")
    (language_dir / "document_term_counts.npz.meta.json").write_text(json.dumps(meta))
    assert blank_recommender(str(tmp_path))._try_load_cached_language("es") is False


def test_videos_by_words_skip_clips_and_can_rank_by_distinct_targets():
    rows = [
        [60] + [0] * 39 + [1] * 110,        # target word 0 said 60 times
        [0] + [1] * 40 + [1] * 109,         # targets 1-40, once each
        [1] * 41 + [0] * 109,               # every target, but a 41-word clip
    ]
    recommender = make_recommender(rows)
    targets = list(range(41))

    by_share = recommender.recommend_videos_by_words(targets, "es")
    assert [v["id"] for v in by_share] == ["video-0", "video-1"]      # clip left out

    by_distinct = recommender.recommend_videos_by_words(targets, "es", rank_by_distinct=True)
    # video-0 has word 0 and, at the start of its tail, word 40.
    assert [(v["id"], v["knownWords"]) for v in by_distinct] == [("video-1", 40), ("video-0", 2)]

    chart = recommender.recommend_videos_by_words(targets, "es", distinct=False)
    assert "newWords" not in chart[0] and chart[0]["percentUnderstood"] > 0


class _WatchEvents:
    """watch_events as PostgREST pages it, for get_watched_videos."""

    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def table(self, name):
        self.asked.append(name)
        return self

    def select(self, *_):
        return self

    def eq(self, *_):
        return self

    def is_(self, column, value):
        self.rows = [r for r in self.rows if r[column] is None]
        return self

    def order(self, *_):
        return self

    def range(self, start, end):
        self.span = (start, end)
        return self

    def execute(self):
        from types import SimpleNamespace
        return SimpleNamespace(data=self.rows[self.span[0]:self.span[1] + 1])


def test_recommendations_leave_out_watched_videos_only(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("REQUIRE_SERVICE_ROLE", "0")
    monkeypatch.setenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.x")
    recommender = blank_recommender()
    recommender.supabase = _WatchEvents([
        {"video_id": "watched", "share": 0.9, "unmarked_at": None},
        {"video_id": "unknown-share", "share": None, "unmarked_at": None},
        {"video_id": "quit", "share": 0.3, "unmarked_at": None},
        {"video_id": "unmarked", "share": 1.0, "unmarked_at": "2026-11-02T10:00:00+00:00"},
    ])
    assert sorted(asyncio.run(recommender.get_watched_videos("user"))) == ["unknown-share", "watched"]
    assert recommender.supabase.asked[0] == "watch_events"
