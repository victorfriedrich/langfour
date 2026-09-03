import json

from scripts.build_corpus_metadata import build


def test_build_adds_titles_to_legacy_manifest(tmp_path):
    filenames = ["first_processed.json", "second_processed.json"]
    for filename, title in zip(filenames, ["First", "Second"]):
        (tmp_path / filename).write_text(json.dumps({"title": title}), encoding="utf-8")

    manifest_path = tmp_path / "document_term_matrix.npz.meta.json"
    manifest_path.write_text(
        json.dumps({
            "filenames": filenames,
            "categories": ["A", "B"],
            "titles": ["Stale", "Stale"],
            "max_word_id": 7,
        }),
        encoding="utf-8",
    )

    build(tmp_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["titles"] == ["First", "Second"]
    assert manifest["filenames"] == filenames
