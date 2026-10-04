#!/usr/bin/env python3
"""Settle flagged dictionary roots: rules first, then a reviewing agent.

    python3 scripts/review_flagged.py prepare es --out /tmp/review   # auto.tsv + batch_*.tsv
    python3 scripts/review_flagged.py apply es /tmp/review/auto.tsv /tmp/review/out_000.tsv

prepare settles what needs no judgement and writes the rest as batch files for
an agent (see docs/plans/flagged-review.md). Decision lines, from either source:

    <id>\tv                      valid
    <id>\ti                      invalid
    <id>\tc\t<correct root>      a real word stored wrongly; merge into that root

apply writes them. A correction is merged (sql/word_status.sql merge_roots) only
when its target exists as a valid root; otherwise the root stays flagged with
the suggestion in status_reason, so a wrong target never captures a form.
"""
import argparse
import os
import re
import sys
from collections import Counter

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

from languages import require_code

ARTICLE = re.compile(r"^(el|la|los|las|el/la) ")
COPY_SHARE = 0.8      # share of a root's forms that another, older root already has
BATCH = 500
FORMS_SHOWN = 6


def bare(root: str) -> str:
    return ARTICLE.sub("", root.lower())


def page(query, size=10_000):
    rows, start = [], 0
    while True:
        chunk = query().range(start, start + size - 1).execute().data
        rows += chunk
        if len(chunk) < size:
            return rows
        start += size


def forms_of(sb, ids: list[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for i in range(0, len(ids), 300):
        for f in (sb.table("wordforms").select("word_id, form")
                  .in_("word_id", ids[i:i + 300]).limit(20_000).execute().data):
            out.setdefault(f["word_id"], []).append(f["form"])
    return out


def rule(root: str, forms: list[str], rid: int, by_bare: dict, owner: dict) -> tuple[str, str] | None:
    """A decision that needs no judgement, or None."""
    # Copy of an older valid root: most of its forms are already that root's.
    if len(forms) >= 3:
        owners = Counter(o for f in forms for o in owner.get(f, ()) if o[0] < rid)
        if owners:
            (_, oroot), n = owners.most_common(1)[0]
            if n / len(forms) >= COPY_SHARE:
                return "c", oroot
    b = bare(root)
    # Same word, different article: "corral" -> "el corral". Exact spelling only:
    # accents tell different words apart (papa/papá, te/té).
    candidates = by_bare.get(b, set()) - {root}
    if len(candidates) == 1:
        return "c", next(iter(candidates))
    if re.search(r"([a-záéíóúüñ])\1\1", b):            # bueeeeeno, chaaaan
        return "i", None
    if re.search(r"[^a-záéíóúüñ-]", b):                 # digits, symbols, several words
        return "i", None
    return None


def prepare(sb, language: str, out: str) -> None:
    os.makedirs(out, exist_ok=True)
    flagged = page(lambda: sb.table("words").select("id, root").eq("language", language)
                   .eq("status", "flagged").order("id"))
    valid = page(lambda: sb.table("words").select("id, root").eq("language", language)
                 .eq("status", "valid").order("id"))
    print(f"{len(flagged):,} flagged, {len(valid):,} valid roots", flush=True)
    by_bare: dict[str, set[str]] = {}
    for v in valid:
        by_bare.setdefault(bare(v["root"]), set()).add(v["root"])
    vforms = forms_of(sb, [v["id"] for v in valid])
    owner: dict[str, set] = {}
    for v in valid:
        for f in vforms.get(v["id"], []):
            owner.setdefault(f, set()).add((v["id"], v["root"]))
    fforms = forms_of(sb, [f["id"] for f in flagged])
    print("forms loaded", flush=True)

    auto, rest = [], []
    for r in flagged:
        forms = sorted(set(fforms.get(r["id"], [])))
        d = rule(r["root"], forms, r["id"], by_bare, owner)
        if d:
            auto.append(f"{r['id']}\t{d[0]}" + (f"\t{d[1]}" if d[1] else ""))
        else:
            rest.append(f"{r['id']}\t{r['root']}\t{', '.join(forms[:FORMS_SHOWN])}")
    with open(os.path.join(out, "auto.tsv"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(auto) + "\n")
    for n, i in enumerate(range(0, len(rest), BATCH)):
        with open(os.path.join(out, f"batch_{n:03}.tsv"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(rest[i:i + BATCH]) + "\n")
    kinds = Counter(line.split("\t")[1] for line in auto)
    print(f"rules settled {len(auto):,} ({dict(kinds)}); {len(rest):,} left for review in "
          f"{-(-len(rest) // BATCH)} batches of {BATCH}")


def apply(sb, language: str, files: list[str]) -> None:
    valid = page(lambda: sb.table("words").select("id, root").eq("language", language)
                 .eq("status", "valid").order("id"))
    by_root = {v["root"]: v["id"] for v in valid}
    words, merges, kept = [], [], 0
    for path in files:
        source = "rule" if os.path.basename(path).startswith("auto") else "review"
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        for line in lines:
            parts = line.split("\t")
            if len(parts) < 2 or not parts[0].isdigit():
                continue
            rid, d = int(parts[0]), parts[1].strip()
            if d in ("v", "i"):
                words.append({"id": rid, "status": "valid" if d == "v" else "invalid",
                              "status_reason": f"{source}: {'valid' if d == 'v' else 'invalid'}",
                              "audit": None})
            elif d == "c" and len(parts) > 2:
                target = parts[2].strip()
                if target in by_root and by_root[target] != rid:
                    merges.append({"src": rid, "dst": by_root[target],
                                   "reason": f"{source}: merged into {target} ({by_root[target]})"})
                else:
                    kept += 1
                    words.append({"id": rid, "status": "flagged", "audit": None,
                                  "status_reason": f"{source} suggests: {target}"})
    # apply_word_audit overwrites audit; keep the stored one.
    ids = [w["id"] for w in words]
    stored = {}
    for i in range(0, len(ids), 500):
        for r in sb.table("words").select("id, audit").in_("id", ids[i:i + 500]).execute().data:
            stored[r["id"]] = r["audit"]
    for w in words:
        w["audit"] = stored.get(w["id"])
    for i in range(0, len(words), 200):
        sb.rpc("apply_word_audit", {"words_payload": words[i:i + 200], "forms_payload": []}).execute()
    for i in range(0, len(merges), 50):
        sb.rpc("merge_roots", {"payload": merges[i:i + 50]}).execute()
    c = Counter(w["status"] for w in words)
    print(f"applied: valid {c['valid']:,}, invalid {c['invalid']:,}, merged {len(merges):,}, "
          f"corrections kept flagged (target not a valid root) {kept:,}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["prepare", "apply"])
    p.add_argument("language")
    p.add_argument("files", nargs="*", help="apply: decision files")
    p.add_argument("--out", help="prepare: directory for auto.tsv and batch files")
    a = p.parse_args()
    from supabase_client import supabase as sb  # verifies service_role
    language = require_code(a.language)
    if a.command == "prepare":
        prepare(sb, language, a.out)
    else:
        apply(sb, language, a.files)


if __name__ == "__main__":
    main()
