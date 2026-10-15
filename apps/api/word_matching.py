"""Attach an unknown transcript token to an existing root, with one Jev request.

Adding a new root (get_word_root -> generate_alternatives -> verify_and_translate)
is several sequential chat-model calls per word and dominated ingest time. The
dictionary is large enough now that most unknown tokens are a missing form of a
root it already has, so parse() asks Jev to pick that root instead:

  1. candidates   roots owning a cached form or root that shares the token's
                  longest prefix. Deliberately crude: Jev does the judging.
  2. Jev          one request: which candidate is the token a form of (or none),
                  and is the token a real word at all.
  3. outcome      a confident pick becomes a new wordform of that root; a token
                  that is clearly not a word is dropped; everything else waits
                  in pending_words. "None of these" never creates a root.

Jev calls real words invalid more often than it calls junk valid (la panera,
el don in the audit), so the real-word cutoff is lenient: it only drops a token
when Jev is close to certain.
"""
import bisect
import os
import unicodedata
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

from database import language_key, word_cache
from languages import require_code

load_dotenv()

URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"   # pinned, like scripts/audit_words.py

MAX_CANDIDATES = 5
MIN_PREFIX = 3
# Measured on 120 held-out Spanish forms and 30 junk tokens (English, names,
# stretched sounds): attaching at p(root) >= 0.6 and p(real) >= 0.35 put 95
# forms under the right root, 4 under a wrong one and no junk anywhere. Junk
# that does pick a root scores p(real) 0.14-0.34; real forms score 0.2 upwards.
ATTACH_ROOT_FROM = 0.6   # p(candidate) for attaching the token to it
ATTACH_REAL_FROM = 0.35  # p(real word) also needed to attach
NOT_A_WORD_BELOW = 0.1   # p(real word) under which the token is dropped
ARTICLES = ("el/la ", "el ", "la ", "los ", "las ", "der ", "die ", "das ",
            "le ", "l'", "il ", "lo ", "gli ", "i ")

LANGUAGE_NAMES = {"es": "Spanish", "fr": "French", "it": "Italian", "de": "German"}


@dataclass
class Match:
    word: str
    candidates: list[str]           # root names, in the order Jev saw them
    root_id: int | None             # the root to attach to, when outcome is "attach"
    outcome: str                    # attach | not_a_word | pending
    p_root: float
    p_real: float
    answers: dict


class CandidateIndex:
    """Sorted cache keys for prefix lookups, built once per parse()."""

    def __init__(self, language: str):
        cache = word_cache[language_key(language)]
        self.roots = {}
        pairs = []
        for root, wid in cache['words'].items():
            self.roots.setdefault(wid, root)
            pairs.append((_fold(_strip_article(root)), wid))
        pairs.extend((_fold(form), wid) for form, wid in cache['wordforms'].items())
        pairs.sort()
        self.keys = [k for k, _ in pairs]
        self.ids = [i for _, i in pairs]

    def drop(self, root_ids: set[int]) -> None:
        """Never offer these roots (audited invalid) as candidates."""
        for wid in root_ids:
            self.roots.pop(wid, None)

    def candidates(self, token: str) -> list[int]:
        """Root ids sharing the longest prefix with `token`, longest first."""
        token = _fold(token)
        found: dict[int, None] = {}
        floor = max(MIN_PREFIX, len(token) // 2)
        for n in range(len(token), floor - 1, -1):
            prefix = token[:n]
            i = bisect.bisect_left(self.keys, prefix)
            while i < len(self.keys) and self.keys[i].startswith(prefix):
                if self.ids[i] in self.roots:
                    found.setdefault(self.ids[i])
                if len(found) >= MAX_CANDIDATES:
                    return list(found)
                i += 1
        return list(found)


def _fold(text: str) -> str:
    """Without accents, so fóllame still meets follar's forms."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def _strip_article(root: str) -> str:
    for article in ARTICLES:
        if root.startswith(article):
            return root[len(article):]
    return root


def questions(language: str, candidates: list[str]) -> dict:
    name = LANGUAGE_NAMES[require_code(language)]
    criteria = {f"r{i}": f"`token` is a form of the headword \"{root}\"."
                for i, root in enumerate(candidates)}
    criteria["none"] = ("None of the listed headwords is the dictionary form of `token`, "
                        "including when `token` is a separate word derived from one of them.")
    # Without the derived-word rule Jev attached 22 of 80 derived words to their
    # base (espaguetización -> el espagueti, eliminación -> eliminar); with it, 6,
    # while held-out forms placed correctly rose from 95 to 100 of 120.
    return {
        "root": {
            "type": "choice",
            "instructions": (f"Which {name} dictionary headword is `token` a form of? A form is "
                             "the same word inflected (plural, gender, verb conjugation, attached "
                             "pronouns) or made diminutive or augmentative, with the same meaning. "
                             "A word derived from a headword with a suffix that changes its meaning "
                             "or word class (a noun made from a verb or another noun, an adverb "
                             "from an adjective) has its own headword."),
            "criteria": criteria,
        },
        "real": {
            "type": "noul",
            "instructions": (f"Is `token` a real {name} word? Regional, colloquial, rare, "
                             "technical and old spellings count."),
            "criteria": {"true": f"A real {name} word, or a common misspelling of one.",
                         "false": "Another language, a proper noun or brand, a stretched-out "
                                  "sound, an acronym, or a fragment."},
        },
    }


def ask_jev(client: httpx.Client, word: str, candidates: list[str], language: str) -> dict:
    state = {"token": word, "headwords": {f"r{i}": r for i, r in enumerate(candidates)}}
    last = None
    for _ in range(3):
        try:
            r = client.post(URL, json={"model": MODEL, "state": state,
                                       "questions": questions(language, candidates)})
            if r.status_code == 200 and "answers" in (body := r.json()):
                return body["answers"]
            last = RuntimeError(f"Jev HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code < 500 and r.status_code not in (408, 429):
                break
        except httpx.HTTPError as e:
            last = e
    raise last


def jev_client() -> httpx.Client:
    return httpx.Client(timeout=30, headers={
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})


def match(client: httpx.Client, index: CandidateIndex, word: str, language: str) -> Match:
    ids = index.candidates(word)
    names = [index.roots[i] for i in ids]
    answers = ask_jev(client, word, names, language)
    probs = answers["root"]["probabilities"]
    p_real = answers["real"]["noul"]
    pick = max((k for k in probs if k != "none"), key=probs.get, default=None)
    p_root = probs.get(pick, 0.0) if pick else 0.0

    if p_real < NOT_A_WORD_BELOW:
        outcome, root_id = "not_a_word", None
    elif pick and p_root >= ATTACH_ROOT_FROM and p_real >= ATTACH_REAL_FROM:
        outcome, root_id = "attach", ids[int(pick[1:])]
    else:
        outcome, root_id = "pending", None
    return Match(word, names, root_id, outcome, p_root, p_real, answers)

