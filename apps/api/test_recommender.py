import builtins

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from recommender import Recommender


def make_recommender(rows, categories=None):
    recommender = Recommender.__new__(Recommender)
    matrix = csr_matrix(np.asarray(rows, dtype=np.int8))
    recommender.languages = ["es"]
    recommender.matrices = {"es": matrix}
    recommender.categories = {
        "es": categories or ["Other"] * matrix.shape[0]
    }
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
