#!/usr/bin/env python3
"""Audit dictionary entries with Jev and write each root's and form's status.

    python3 scripts/audit_words.py es                  # every unverified root
    python3 scripts/audit_words.py es --limit 500      # the next 500
    python3 scripts/audit_words.py es --ids 101428 7731 --dry-run

Jev (TypeSafe, on OpenRouter's Decisions API) is a decision model: it answers
typed questions about a state with probabilities, not text. One request per
root carries three kinds of question about the same state (the root and its
forms):

  entry   choice: valid / questionable / invalid, for the entry as a whole
  root    yes/no: is the root a correctly spelled word in dictionary form
  form_N  yes/no per form: does this form belong to this root

Statuses (sql/word_status.sql):
  valid    p(valid) > VALID_ABOVE
  invalid  p(invalid) >= INVALID_FROM and p(root) < INVALID_ROOT_BELOW
  flagged  everything else; Claude reviews these and sets valid or invalid
A form scoring below FORM_FLAG_BELOW is flagged on its own, under any root.
The thresholds come from a hand-labelled sample of 128 roots: Jev never called
junk valid, but it does call real words invalid, so invalid needs both signals.

Forms containing a space are not sent: transcripts are matched one word at a
time, so they can never link, and they are left for a cleanup rule. The raw
probabilities are stored in words.audit / wordforms.audit_score, so the
thresholds can be re-tuned without new requests. Only unverified roots are
picked up, so a run can be stopped and resumed.
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

from languages import require_code

URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"      # pinned: the thresholds were measured against it

VALID_ABOVE = 0.7
INVALID_FROM = 0.7
INVALID_ROOT_BELOW = 0.1
FORM_FLAG_BELOW = 0.3

LANGUAGE_NAMES = {"es": "Spanish", "fr": "French", "it": "Italian", "de": "German"}

# Wording chosen on a hand-labelled sample of 125 roots. Putting these rules in
# the root question too, or naming the storage conventions (article, infinitive)
# in the entry question, pushed ordinary words to "questionable": 100 of 128
# roots flagged instead of 70. No examples: they bias the answer toward them.
NO_FORMS = ("Adverbs, pronouns, conjunctions, prepositions and interjections have no "
            "inflected forms, so an empty form list is normal for them.")
DIMINUTIVES = ("A diminutive or augmentative is not a headword of its own: it belongs "
               "under its base word as a form.")


def questions(language: str, forms: list[str]) -> dict:
    name = LANGUAGE_NAMES[language]
    q = {
        "entry": {
            "type": "choice",
            "instructions": (f"Is this a real {name} word, stored correctly as a dictionary "
                             f"headword? Regional, colloquial, rare and technical words count. "
                             f"{NO_FORMS} {DIMINUTIVES}"),
            "criteria": {
                "valid": f"A real {name} word in dictionary form, and its forms are genuine forms of it.",
                "questionable": (f"A real {name} word, but stored in the wrong dictionary form "
                                 "or with wrong forms, or unclear."),
                "invalid": (f"Not a {name} word: another language, a proper noun or brand, a "
                            "misspelling, an elongated sound, an acronym, or a fragment."),
            },
        },
        "root": {
            "type": "noul",
            "instructions": f"Is the root a correctly spelled {name} word in dictionary form?",
            "criteria": {"true": f"A correctly spelled {name} word in dictionary form.",
                         "false": "Misspelled, another language, a proper noun, or not in dictionary form."},
        },
    }
    for i, form in enumerate(forms):
        q[f"form_{i}"] = {
            "type": "noul",
            "instructions": f'Is "{form}" a form of this root?',
            "criteria": {"true": "An inflection, diminutive or augmentative of this root, correctly spelled.",
                         "false": "A misspelling, a different word, or another language."},
        }
    return q


def ask(client: httpx.Client, state: dict, q: dict) -> dict:
    """One decision request, retried on rate limits and transient errors."""
    for attempt in range(5):
        try:
            r = client.post(URL, json={"model": MODEL, "state": state, "questions": q})
            if r.status_code == 200:
                body = r.json()
                if "answers" in body:
                    return body
            if r.status_code not in (408, 429, 500, 502, 503, 504) and r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        except httpx.HTTPError:
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError("Jev did not answer after 5 attempts")


def verdict(entry: dict, client: httpx.Client, language: str) -> tuple[dict, list[dict], float]:
    """The root's row and its forms' rows for apply_word_audit, and the cost."""
    forms = [f for f in entry["forms"] if " " not in f["form"]]
    state = {"root": entry["root"], "forms": [f["form"] for f in forms]}
    body = ask(client, state, questions(language, state["forms"]))
    a = body["answers"]
    p = a["entry"]["probabilities"]
    root_p = a["root"]["noul"]

    if p["valid"] > VALID_ABOVE:
        status, reason = "valid", f"jev valid {p['valid']:.2f}"
    elif p["invalid"] >= INVALID_FROM and root_p < INVALID_ROOT_BELOW:
        status, reason = "invalid", f"jev invalid {p['invalid']:.2f}, root {root_p:.2f}"
    else:
        status = "flagged"
        reason = (f"jev unsure: valid {p['valid']:.2f}, questionable {p['questionable']:.2f}, "
                  f"invalid {p['invalid']:.2f}, root {root_p:.2f}")

    root_row = {"id": entry["id"], "status": status, "status_reason": reason,
                "audit": {"model": body.get("model"), "choice": a["entry"]["choice"],
                          "p": p, "root": root_p}}
    form_rows = []
    for i, f in enumerate(forms):
        score = a[f"form_{i}"]["noul"]
        if score < FORM_FLAG_BELOW:
            form_rows.append({"id": f["id"], "status": "flagged", "score": score,
                              "status_reason": f"jev: form of this root {score:.2f}"})
        else:
            form_rows.append({"id": f["id"], "status": "valid", "score": score, "status_reason": None})
    return root_row, form_rows, (body.get("usage") or {}).get("cost") or 0.0


def unverified(sb, language: str, after: int, page: int) -> list[dict]:
    """The next page of unverified roots with their forms."""
    words = (sb.table("words").select("id, root").eq("language", language)
             .eq("status", "unverified").gt("id", after).order("id").limit(page).execute().data)
    return attach_forms(sb, words)


def attach_forms(sb, words: list[dict]) -> list[dict]:
    forms: dict[int, list[dict]] = {}
    # 50 roots a request: a verb carries ~30-100 forms, and a larger chunk could
    # run past the server's row cap and silently drop forms.
    for i in range(0, len(words), 50):
        ids = [w["id"] for w in words[i:i + 50]]
        for f in (sb.table("wordforms").select("id, word_id, form").in_("word_id", ids)
                  .limit(10_000).execute().data):
            forms.setdefault(f["word_id"], []).append(f)
    return [{**w, "forms": forms.get(w["id"], [])} for w in words]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("language")
    p.add_argument("--ids", type=int, nargs="+", help="audit these roots, whatever their status")
    p.add_argument("--limit", type=int, help="stop after this many roots")
    p.add_argument("--workers", type=int, default=32)
    p.add_argument("--dry-run", action="store_true", help="print verdicts, write nothing")
    p.add_argument("--out", help="also append every verdict to this JSONL file")
    a = p.parse_args()

    from supabase_client import supabase as sb  # verifies service_role
    language = require_code(a.language)
    client = httpx.Client(timeout=120, headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
    out = open(a.out, "a", encoding="utf-8") if a.out else None  # noqa: SIM115 -- closed at the end of main

    def pages():
        if a.ids:
            yield attach_forms(sb, sb.table("words").select("id, root").in_("id", a.ids).execute().data)
            return
        after = 0
        while True:
            batch = unverified(sb, language, after, 500)
            if not batch:
                return
            yield batch
            after = batch[-1]["id"]

    done, cost, totals, started = 0, 0.0, {}, time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for batch in pages():
            if a.limit:
                batch = batch[:max(0, a.limit - done)]
            if not batch:
                break
            def safe(e):
                # One failing root stays unverified and is picked up next run.
                try:
                    return verdict(e, client, language)
                except Exception as exc:
                    print(f"  {e['root']}: {exc}", flush=True)
                    return None
            pairs = [(r, e) for r, e in zip(pool.map(safe, batch), batch, strict=True) if r]
            results, batch_ok = [r for r, _ in pairs], [e for _, e in pairs]
            roots = [r for r, _, _ in results]
            forms = [f for _, fs, _ in results for f in fs]
            if not a.dry_run:
                sb.rpc("apply_word_audit", {"words_payload": roots, "forms_payload": forms}).execute()
            for (root, fs, c), entry in zip(results, batch_ok, strict=True):
                cost += c
                totals[root["status"]] = totals.get(root["status"], 0) + 1
                if out:
                    out.write(json.dumps({"root": entry["root"], **root,
                                          "forms": {f["form"]: r["score"] for f, r in
                                                    zip([f for f in entry["forms"] if " " not in f["form"]], fs, strict=True)}},
                                         ensure_ascii=False) + "\n")
                if a.dry_run:
                    flagged = [f["form"] for f, r in zip([f for f in entry["forms"] if " " not in f["form"]], fs, strict=True)
                               if r["status"] == "flagged"]
                    print(f"  {entry['root'][:28]:28} {root['status']:8} {root['status_reason']}"
                          + (f"  forms flagged: {', '.join(flagged)}" if flagged else ""))
            done += len(batch)
            print(f"{done:,} roots  " + "  ".join(f"{k} {v:,}" for k, v in sorted(totals.items()))
                  + f"  [${cost:.4f}, {time.time() - started:.0f}s]", flush=True)
            if a.limit and done >= a.limit:
                break
    if out:
        out.close()


if __name__ == "__main__":
    main()
