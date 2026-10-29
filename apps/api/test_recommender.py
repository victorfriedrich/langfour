import asyncio
import builtins
import json

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from recommender import Recommender


def make_recommender(rows, categories=None, titles=None):
    recommender = Recommender.__new__(Recommender)
    matrix = csr_matrix(np.asarray(rows, dtype=np.int8))
    recommender.languages = ["es"]
    recommender.matrices = {"es": matrix}
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
    recommender.total_words_per_doc = {
        "es": np.asarray(matrix.sum(axis=1)).ravel()
    }
    recommender.hidden_videos = set()
    return recommender


def test_hidden_videos_are_never_recommended():
    recommender = make_recommender([np.ones(150, dtype=np.int8)] * 3)
    recommender.hidden_videos = {"video-1"}

    async def get_known_words(_user_id):
        return [0]

    async def get_seen_videos(_user_id):
        return []

    recommender.get_known_words = get_known_words
    recommender.get_seen_videos = get_seen_videos

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

    async def get_seen_videos(_user_id):
        return []

    recommender.get_known_words = get_known_words
    recommender.get_seen_videos = get_seen_videos

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

    recommender = Recommender.__new__(Recommender)
    recommender.base_folder = str(tmp_path)
    recommender.languages = ["es"]
    recommender.blacklisted_files = set()
    recommender.documents = {}
    recommender.filenames = {}
    recommender.categories = {}
    recommender.titles = {}
    recommender.max_word_ids = {}
    recommender.matrices = {}
    recommender.total_words_per_doc = {}
    recommender._ensure_language_loaded("es")

    manifest_path = language_dir / "document_term_matrix.npz.meta.json"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["titles"] == ["A trip"]

    transcript_path.write_text("not valid JSON", encoding="utf-8")
    loaded = Recommender.__new__(Recommender)
    loaded.base_folder = str(tmp_path)
    loaded.blacklisted_files = set()
    loaded.documents = {}
    loaded.filenames = {}
    loaded.categories = {}
    loaded.titles = {}
    loaded.max_word_ids = {}
    loaded.matrices = {}
    loaded.total_words_per_doc = {}

    assert loaded._try_load_cached_language("es") is True
    assert loaded.titles["es"] == ["A trip"]



def test_saved_words_page_through_the_users_list():
    rows = [{"user_id": "me", "word_id": i} for i in range(1500)]
    rows.append({"user_id": "other", "word_id": 9999})

    class Query:
        def __init__(self):
            self.filters = {}

        def select(self, _cols):
            return self

        def eq(self, column, value):
            self.filters[column] = value
            return self

        def order(self, _column):
            return self

        def range(self, start, end):
            self.window = (start, end)
            return self

        def execute(self):
            matching = [r for r in rows if all(r[k] == v for k, v in self.filters.items())]
            start, end = self.window
            return type("Response", (), {"data": matching[start:end + 1]})

    class Client:
        def table(self, name):
            assert name == "userwords"
            return Query()

    recommender = make_recommender([[1]])
    recommender.supabase = Client()

    saved = asyncio.run(recommender.get_saved_words("me"))
    assert sorted(saved) == list(range(1500))
