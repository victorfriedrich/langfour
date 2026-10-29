"""
What an AI app connected over MCP can learn about the user's vocabulary, and
what it reports back about texts the user read with it.

  - get_vocabulary: counts and a list of known, learning or due words
    (mcp_vocabulary in sql/mcp_vocabulary.sql).
  - score_text: how much of a text the user would understand, and which of its
    words they're learning or haven't met. Words are classified with the
    reader's rules (classify_words_for in sql/classify_words.sql): names,
    acronyms and other non-vocabulary are left out, a spelling of several
    words counts as known if any of them is.
  - record_exposure: one word_events 'exposure' row per learning or new word of
    a text the user chose to read (docs/plans/learner-word-data-model.md:
    exposure counts only what the user chose to read or hear, never every
    word an AI wrote).
  - set_word_status: move words of the user's list between learning and
    known, as the web app's "Move to known" does. Back to learning, the
    userwords trigger gives the word a Langfour card again.

The API runs these with the service role on behalf of the OAuth user, so every
query names the user explicitly.
"""

import re
from collections import Counter
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

from supabase_client import supabase

Language = Literal["es", "de", "it", "fr"]
SOURCE = "chatgpt"
MAX_TEXT = 20_000
# Words listed per status in a text's score; the percentages cover all.
LISTED = 40

# Letters only: digits, punctuation and apostrophes split words, so French
# "l'homme" yields "l" (not vocabulary) and "homme".
_WORD = re.compile(r"[^\W\d_]+")

_CLASSIFY_CHUNK = 1000  # tokens per classify_words_for call, as in the extension
_IN_CHUNK = 200


def _chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

class VocabularyCounts(BaseModel):
    known: int
    learning: int
    due: int  # learning words whose review is due now


class VocabularyWord(BaseModel):
    word: str
    translation: str | None
    status: Literal["known", "learning"]
    due: bool


class Vocabulary(BaseModel):
    language: str | None  # None: no language given and the user has no default
    counts: VocabularyCounts
    words: list[VocabularyWord]


class TextWord(BaseModel):
    word: str  # dictionary form
    translation: str | None
    occurrences: int


class TextScore(BaseModel):
    running_words: int     # words of the text that are vocabulary, repeats included
    known_percent: float   # of running_words
    learning_percent: float
    new_percent: float     # includes words the user turned off
    learning: list[TextWord]  # most frequent first
    new: list[TextWord]


class ExposureSummary(BaseModel):
    recorded: int  # distinct learning or new words logged as read


class StatusChange(BaseModel):
    changed: list[str]    # now in the requested status, including any already in it
    not_found: list[str]  # not in the user's list in that language, or turned off


# ---------------------------------------------------------------------------
# Storage. Like practice.PracticeStore: everything that touches Supabase is
# here, so the logic below runs against an in-memory stand-in in tests.
# ---------------------------------------------------------------------------

class VocabularyStore:
    def __init__(self, client):
        self.db = client

    def vocabulary(self, user_id: str, language: str | None, status: str, limit: int) -> dict:
        return self.db.rpc("mcp_vocabulary", {
            "p_user_id": user_id, "p_language": language,
            "p_status": status, "p_limit": limit,
        }).execute().data

    def classify(self, user_id: str, language: str, tokens: list[str]) -> dict[str, tuple[int, str]]:
        """token -> (word_id, status) for the tokens that are vocabulary."""
        found: dict[str, tuple[int, str]] = {}
        for chunk in _chunks(tokens, _CLASSIFY_CHUNK):
            rows = self.db.rpc("classify_words_for", {
                "p_user_id": user_id, "language_filter": language, "tokens": chunk,
            }).execute().data
            for r in rows or []:
                found[r["token"]] = (r["word_id"], r["status"])
        return found

    def words(self, word_ids: list[int]) -> dict[int, dict]:
        """word_id -> {root, translation}."""
        out: dict[int, dict] = {}
        for chunk in _chunks(word_ids, _IN_CHUNK):
            res = self.db.table("words").select("id, root, translation").in_("id", chunk).execute()
            for r in res.data or []:
                out[r["id"]] = r
        return out

    def insert_events(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        res = self.db.table("word_events").insert(rows).execute()
        return len(res.data or [])

    def user_words(self, user_id: str, language: str, roots: list[str]) -> list[dict]:
        """The user's learning and known words with these roots: [{word_id, root}]."""
        res = (self.db.table("userwords").select("word_id, words!inner(root, language)")
               .eq("user_id", user_id).eq("words.language", language)
               .in_("status", ["learning", "known"]).in_("words.root", roots).execute())
        return [{"word_id": r["word_id"], "root": r["words"]["root"]} for r in res.data or []]

    def set_status(self, user_id: str, word_ids: list[int], status: str) -> None:
        # Not set_userwords_status: it updates auth.uid()'s words, and the API
        # runs as the service role. Rows already in the status are left alone,
        # so the userwords trigger doesn't touch their cards.
        (self.db.table("userwords").update({"status": status})
         .eq("user_id", user_id).in_("word_id", word_ids).neq("status", status).execute())


def get_vocabulary_store() -> VocabularyStore:
    return VocabularyStore(supabase)


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

def get_vocabulary(store: VocabularyStore, user_id: str, language: str | None,
                   status: Literal["due", "learning", "known"], limit: int) -> Vocabulary:
    return Vocabulary.model_validate(store.vocabulary(user_id, language, status, limit))


def _classified(store: VocabularyStore, user_id: str, language: str,
                text: str) -> list[tuple[int, str]]:
    """(word_id, status) for every vocabulary word of the text, in order."""
    tokens = _WORD.findall(text)
    classes = store.classify(user_id, language, sorted(set(tokens)))
    return [classes[t] for t in tokens if t in classes]


def _percent(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def score_text(store: VocabularyStore, user_id: str, language: str, text: str) -> TextScore:
    running = _classified(store, user_id, language, text)
    by_status = Counter(status for _, status in running)
    occurrences = Counter(running)

    def listed(status: str) -> list[TextWord]:
        ids = [w for (w, s), _ in occurrences.most_common() if s == status][:LISTED]
        info = store.words(ids)
        return [TextWord(word=info[w]["root"], translation=info[w].get("translation"),
                         occurrences=occurrences[(w, status)])
                for w in ids if w in info]

    total = len(running)
    return TextScore(
        running_words=total,
        known_percent=_percent(by_status["known"], total),
        learning_percent=_percent(by_status["learning"], total),
        new_percent=_percent(by_status["new"] + by_status["ignored"], total),
        learning=listed("learning"),
        new=listed("new"),
    )


def record_exposure(store: VocabularyStore, user_id: str, language: str,
                    text: str) -> ExposureSummary:
    word_ids = sorted({w for w, status in _classified(store, user_id, language, text)
                       if status in ("learning", "new")})
    recorded = store.insert_events([
        {"user_id": user_id, "word_id": w, "kind": "exposure", "source": SOURCE}
        for w in word_ids
    ])
    return ExposureSummary(recorded=recorded)


def set_word_status(store: VocabularyStore, user_id: str, language: str, words: list[str],
                    status: Literal["known", "learning"]) -> StatusChange:
    asked = list(dict.fromkeys(w.strip() for w in words if w.strip()))
    # Every word with a given root moves: homographs are listed under one spelling.
    rows = store.user_words(user_id, language, asked)
    if rows:
        store.set_status(user_id, sorted({r["word_id"] for r in rows}), status)
    found = {r["root"] for r in rows}
    return StatusChange(changed=[w for w in asked if w in found],
                        not_found=[w for w in asked if w not in found])
