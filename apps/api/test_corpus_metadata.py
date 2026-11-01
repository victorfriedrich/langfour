import json

import pytest

from scripts.build_corpus_metadata import build


def test_build_adds_titles_to_legacy_manifest(tmp_path):
    filenames = ["first_processed.json", "second_processed.json"]
    for filename, title in zip(filenames, ["First", "Second"], strict=False):
        (tmp_path / filename).write_text(json.dumps({"title": title}), encoding="utf-8")

    manifest_path = tmp_path / "document_term_counts.npz.meta.json"
    manifest_path.write_text(
        json.dumps({
            "filenames": filenames,
            "categories": ["A", "B"],
            "titles": ["Stale", "Stale"],
            "max_word_id": 7,
            "weights": "counts",
        }),
        encoding="utf-8",
    )

    build(tmp_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["titles"] == ["First", "Second"]
    assert manifest["filenames"] == filenames


def test_packing_refuses_a_corpus_without_the_counts_matrix(tmp_path):
    # Only the binary matrix from before counts: every boot would rebuild.
    (tmp_path / "document_term_matrix.npz.meta.json").write_text(
        json.dumps({"filenames": [], "categories": [], "titles": [], "max_word_id": 0}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="counts matrix"):
        build(tmp_path)

    (tmp_path / "document_term_counts.npz.meta.json").write_text(
        json.dumps({"filenames": [], "categories": [], "titles": [], "max_word_id": 0}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="not a counts matrix"):
        build(tmp_path)
