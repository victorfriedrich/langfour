import builtins
import asyncio
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
    return recommender


def test_categories_come_from_loaded_manifest_data():
    recommender = make_recommender(
        [[1], [1], [1], [0]],
        ["Travel", "Cooking", "Travel", "Unknown"],
    )

    assert recommender.get_categories("es") == [
        {"category": "Cooking", "icon": None},
        {"category": "Travel", "icon": None},
    ]


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
