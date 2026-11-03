#!/usr/bin/env python3
"""Add row-aligned video titles, channel names and lengths to an existing
matrix manifest (recommender.Recommender._cached_details reads the last two)."""

import json
import sys
from pathlib import Path

# recommender.MATRIX_FILE and MATRIX_WEIGHTS, repeated so pack_corpus.sh can
# run this with the system python3, without the API's dependencies.
MANIFEST = "document_term_counts.npz.meta.json"
WEIGHTS = "counts"


def build(language_dir: Path) -> None:
    manifest_path = language_dir / MANIFEST
    # Packing without the counts matrix ships a corpus every API boot has to
    # rebuild (13k transcripts read before serving), so refuse instead.
    if not manifest_path.exists():
        raise SystemExit(
            f"{manifest_path} is missing: start the API once against this data "
            "dir so the recommender builds the counts matrix, then pack again."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("weights") != WEIGHTS:
        raise SystemExit(f"{manifest_path} is not a counts matrix; rebuild it before packing.")
    filenames = manifest["filenames"]

    titles, creators, lengths = [], [], []
    for filename in filenames:
        data = json.loads((language_dir / filename).read_text(encoding="utf-8"))
        title = data.get("title", "")
        titles.append(title if isinstance(title, str) else "")
        # As file_manager.video_details.
        creator, length = data.get("creator"), data.get("length")
        creators.append(creator.strip() if isinstance(creator, str) else "")
        lengths.append(int(length) if isinstance(length, (int, float)) and length > 0 else None)

    manifest["titles"] = titles
    manifest["creators"] = creators
    manifest["lengths"] = lengths
    temporary_path = manifest_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(manifest_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} <processed-language-dir>")
    build(Path(sys.argv[1]))
