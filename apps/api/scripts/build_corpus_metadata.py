#!/usr/bin/env python3
"""Add row-aligned video titles to an existing matrix manifest."""

import json
import sys
from pathlib import Path


def build(language_dir: Path) -> None:
    manifest_path = language_dir / "document_term_matrix.npz.meta.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    filenames = manifest["filenames"]

    titles = []
    for filename in filenames:
        data = json.loads((language_dir / filename).read_text(encoding="utf-8"))
        title = data.get("title", "")
        titles.append(title if isinstance(title, str) else "")

    manifest["titles"] = titles
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
