import dataclasses

import numpy as np
import pytest
from scipy.sparse import csr_matrix

import channel_similarity
from language_index import LanguageIndex, video_id_of


def build(rows, **columns):
    matrix = csr_matrix(np.asarray(rows, dtype=np.int16))
    n = matrix.shape[0]
    args = {"filenames": [f"v{i}_processed.json" for i in range(n)],
            "categories": ["Other"] * n, "titles": [f"T{i}" for i in range(n)]}
    args.update(columns)
    return LanguageIndex.build("es", counts=matrix, **args)


def test_every_column_lines_up_with_the_matrix_rows():
    index = build([[2, 0, 1], [0, 3, 0]], creators=["A", ""], lengths=[60, None])

    assert len(index) == 2 and index.width == 3
    assert index.video_ids == ("v0", "v1")
    assert dict(index.rows) == {"v0": 0, "v1": 1}
    assert index.spoken.tolist() == [3, 3] and index.distinct.tolist() == [2, 1]
    assert index.presence.toarray().tolist() == [[1, 0, 1], [0, 1, 0]]
    assert index.max_word_id == 2


def test_blank_channel_names_and_lengths_when_the_manifest_has_none():
    index = build([[1], [1]])
    assert index.creators == ("", "") and index.lengths == (None, None)


@pytest.mark.parametrize("column", ["filenames", "categories", "titles", "creators", "lengths"])
def test_a_column_of_the_wrong_length_is_refused(column):
    with pytest.raises(ValueError, match=column):
        build([[1], [1]], **{column: ["only one"]})


def test_a_video_twice_is_refused():
    with pytest.raises(ValueError, match="twice"):
        build([[1], [1]], filenames=["v_processed.json", "v_processed.json"])


def test_an_index_cannot_be_changed_in_place():
    index = build([[1]])
    with pytest.raises(dataclasses.FrozenInstanceError):
        index.titles = ("other",)
    with pytest.raises(TypeError):
        index.rows["v9"] = 0


def test_score_counts_repeats_for_the_share_and_distinct_words_for_new():
    index = build([[50] + [1] * 149])
    ratios, new, known = index.score([0, 1, 999])  # 999 has no column
    assert ratios[0] == pytest.approx(51 / 199)
    assert (new[0], known[0]) == (148, 2)
    assert index.score([0], distinct=False)[1:] == (None, None)


def test_video_id_of_strips_the_transcript_suffix():
    assert video_id_of("dQw4w9WgXcQ_processed.json") == "dQw4w9WgXcQ"


def test_similarity_space_is_rebuilt_for_a_new_index_only(monkeypatch):
    channel_similarity._cache.clear()
    index = build([[1, 1], [1, 0]], creators=["A", "B"])
    first = channel_similarity.space(index)
    assert channel_similarity.space(index) is first
    assert channel_similarity.space(dataclasses.replace(index)) is not first
