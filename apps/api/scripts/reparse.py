#!/usr/bin/env python3
"""Re-link every word of the stored transcripts to the current dictionary.

    python3 scripts/reparse.py es              # dry run: what would change, per word
    python3 scripts/reparse.py es --write      # rewrite the changed files
    python3 scripts/reparse.py es --write VIDEO_ID

Each transcript in data/processed/<lang>/ stores, for every word, the id of the
root it was linked to at ingestion. Merges, renames and status changes in the
dictionary do not reach those files, so a token keeps pointing at whatever it
matched back then ("ha" at a standalone root instead of haber). This resolves
every word token again, the way the word cache does (root name first, then
forms, the older root winning a shared form), with two differences that only
hold here: an invalid root never matches, and a token nothing matches gets no
id. After writing, delete the recommender's document_term_matrix.npz so it is
rebuilt from the new ids.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from languages import to_code
from paths import processed_dir

WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")


def page(query, size=10_000):
    rows, start = [], 0
    while True:
        chunk = query().range(start, start + size - 1).execute().data
        rows += chunk
        if len(chunk) < size:
            return rows
        start += size


def resolver(sb, language: str):
    """token -> root id (or None), plus id -> root text for reporting."""
    roots = page(lambda: sb.table("words").select("id, root, status")
                 .eq("language", language).order("id"))
    names: dict[str, int] = {}
    for r in roots:
        if r["status"] != "invalid":
            names.setdefault(r["root"].lower(), r["id"])
    live = [r["id"] for r in roots if r["status"] != "invalid"]
    forms: dict[str, int] = {}
    for i in range(0, len(live), 300):
        rows = (sb.table("wordforms").select("word_id, form, status")
                .in_("word_id", live[i:i + 300]).limit(20_000).execute().data)
        for f in sorted(rows, key=lambda f: f["word_id"]):
            if f["status"] != "invalid":
                forms.setdefault(f["form"].lower(), f["word_id"])
    text = {r["id"]: r["root"] for r in roots}

    def resolve(token: str) -> int | None:
        w = token.lower()
        return names.get(w) or names.get(w.title()) or forms.get(w)
    return resolve, text


def reparse(content: list[dict], resolve) -> list[tuple[str, int | None, int | None]]:
    """Re-link word tokens in place; return (word, old, new) for each change."""
    changes = []
    for item in content:
        token = item.get("content") or ""
        if not WORD.fullmatch(token):
            continue
        old = item.get("id")
        new = resolve(token)
        if new != old:
            changes.append((token.lower(), old, new))
            if new is None:
                item.pop("id", None)
            else:
                item["id"] = new
    return changes


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("language")
    p.add_argument("video_id", nargs="?")
    p.add_argument("--write", action="store_true", help="rewrite changed files (default: dry run)")
    a = p.parse_args()
    from supabase_client import supabase as sb  # verifies service_role
    language = to_code(a.language)
    folder = processed_dir(language)
    resolve, text = resolver(sb, language)

    names = [f"{a.video_id}_processed.json"] if a.video_id else sorted(
        f for f in os.listdir(folder) if f.endswith("_processed.json"))
    per_word: Counter = Counter()
    tokens = changed_tokens = changed_files = 0
    for name in names:
        path = os.path.join(folder, name)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        tokens += sum(1 for t in data["content"] if WORD.fullmatch(t.get("content") or ""))
        changes = reparse(data["content"], resolve)
        if not changes:
            continue
        changed_files += 1
        changed_tokens += len(changes)
        for word, old, new in changes:
            per_word[(word, old, new)] += 1
        if a.write:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)

    label = lambda i: "-" if i is None else text.get(i, f"#{i}")  # noqa: E731
    print(f"{len(names):,} files, {tokens:,} word tokens; {changed_tokens:,} tokens "
          f"({changed_tokens / max(tokens, 1):.1%}) in {changed_files:,} files "
          f"{'rewritten' if a.write else 'would change'}")
    for (word, old, new), n in per_word.most_common(40):
        print(f"  {n:>8,}  {word:14} {label(old)} -> {label(new)}")


if __name__ == "__main__":
    main()
