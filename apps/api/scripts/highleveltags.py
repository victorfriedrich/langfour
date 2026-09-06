#!/usr/bin/env python3
"""Assign each transcript the high-level category the app browses by.

    python3 scripts/highleveltags.py <language> [--redo]

This is the only writer of the `category` field. videoparsing.py stores raw
`tags` at ingest but no category, and file_manager.py reads `category` to build
the category list, falling back to "Unknown" -- so a freshly ingested video has
no category until this runs. It is a pipeline stage that was never automated,
not a one-time backfill.

By default it only fills in files that have no category, so it is cheap to re-run
after an ingest. Pass --redo to also revisit the verdicts worth a second attempt.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nlp_processing import get_high_level_tag  # noqa: E402
from paths import processed_dir  # noqa: E402

# Verdicts worth a second attempt when --redo is passed.
#
#   "Failed"        get_high_level_tag returns this when the model refuses or its
#                   reply does not parse. Roughly 7% of the Spanish corpus.
#   "Entertainment" a legacy value: it is not in nlp_processing.VALID_CATEGORIES
#                   any more, so the classifier can no longer produce it.
#   "Other"         the classifier's own catch-all, worth re-asking after a
#                   prompt change.
#
# Reaching any of them needed a fix. The skip condition was `current_cat is not
# None`, which stepped over every file that had a category at all -- including
# the failures -- while the docstring claimed Entertainment and Other were
# revisited. So the (b) half of that promise had never once run.
REDO_CATEGORIES = {"Entertainment", "Other", "Failed"}


def update_files_with_high_level_tag(base_folder: str, redo: bool = False):
    """Assign a category to files that have none, or to weak ones when redo."""
    for root, _, files in os.walk(base_folder):
        for file in files:
            if not file.endswith("_processed.json"):
                continue

            file_path = os.path.join(root, file)

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                current_cat = data.get("category")
                if current_cat is not None and not (redo and current_cat in REDO_CATEGORIES):
                    continue

                title = data.get("title", "")
                tags = data.get("tags", [])

                high_level_tag = get_high_level_tag(title, tags)

                # Overwrite or insert the category
                data["category"] = high_level_tag

                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                print(f"Updated {file_path}: {current_cat!r} → {high_level_tag!r}")

            except Exception as e:
                print(f"Error processing {file_path}: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/highleveltags.py <language> [--redo]")
        sys.exit(1)

    update_files_with_high_level_tag(
        str(processed_dir(sys.argv[1])), redo="--redo" in sys.argv[2:]
    )
