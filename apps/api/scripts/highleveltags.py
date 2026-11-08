#!/usr/bin/env python3
"""Assign each transcript the high-level category the app browses by.

    python3 scripts/highleveltags.py <language> [--redo | --all]

This is the only writer of the `category` field. videoparsing.py stores raw
`tags` at ingest but no category, and file_manager.py reads `category` to build
the category list, falling back to "Unknown" -- so a freshly ingested video has
no category until this runs. It is a pipeline stage that was never automated,
not a one-time backfill. The category itself comes from Jev (video_category.py).

By default it only fills in files that have no category, so it is cheap to re-run
after an ingest. Pass --redo to also revisit the verdicts worth a second attempt,
or --all to classify every file again after a change to video_category.py.

Production only sees the new labels once the corpus is packed and uploaded from
this disk (scripts/pack_corpus.sh, then scripts/upload_corpus.sh) and the API
restarts. Pack from the data dir this ran on: worktrees keep their own corpus
copies, and on 2026-11-04 one that was never relabelled was packed and
uploaded, so the PR that took eating videos out of Cooking never reached
the Videos page.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

import video_category
from paths import processed_dir

# Verdicts worth a second attempt when --redo is passed.
#
#   "Failed"        a legacy value: the old LLM classifier returned it when the
#                   model refused or its reply did not parse.
#   "Entertainment" a legacy value: it is not in video_category.CATEGORIES, so
#                   Jev can no longer produce it.
#   "Other"         the catch-all, worth re-asking after a prompt change.
REDO_CATEGORIES = {"Entertainment", "Other", "Failed"}

PARALLEL = 16   # Jev requests in flight


def wanted(file_path: str, redo: bool, redo_all: bool) -> bool:
    try:
        with open(file_path, encoding="utf-8") as f:
            current_cat = json.load(f).get("category")
    except (OSError, ValueError):
        return True   # update() reports it, rather than one bad file ending the run
    return redo_all or current_cat is None or (redo and current_cat in REDO_CATEGORIES)


def update_files_with_high_level_tag(base_folder: str, redo: bool = False,
                                     redo_all: bool = False):
    """Assign a category to files that have none, or to weak ones when redo."""
    paths = [os.path.join(root, file)
             for root, _, files in os.walk(base_folder)
             for file in files if file.endswith("_processed.json")]
    paths = [p for p in paths if wanted(p, redo, redo_all)]
    print(f"{len(paths)} files to classify")
    http = video_category.client()

    def update(file_path: str) -> None:
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            current_cat = data.get("category")
            category = video_category.classify(http, data)
            if category == current_cat:
                return
            data["category"] = category
            # Written aside and renamed, so an interrupted run never leaves a
            # half-written transcript.
            tmp = file_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, file_path)
            print(f"Updated {file_path}: {current_cat!r} → {category!r}")
        except Exception as e:
            # Left as it was; an uncategorised file is picked up by the next run.
            print(f"Error processing {file_path}: {e}")

    with ThreadPoolExecutor(PARALLEL) as pool:
        list(pool.map(update, paths))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/highleveltags.py <language> [--redo | --all]")
        sys.exit(1)

    load_dotenv()
    update_files_with_high_level_tag(
        str(processed_dir(sys.argv[1])), redo="--redo" in sys.argv[2:],
        redo_all="--all" in sys.argv[2:],
    )
