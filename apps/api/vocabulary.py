"""
What an AI app connected over MCP can learn about the user's vocabulary, and
what it reports back about texts the user read with it.

  - get_vocabulary: counts and a list of known, learning or due words
    (mcp_vocabulary in sql/mcp_vocabulary.sql), plus the words whose last
    practice answer was wrong, with the AI app's note: the mistakes to revise,
    known words included, since those have no card to bring back.
  - score_text: how much of a text the user would understand, and which of its
    words they're learning or haven't met. Words are classified with the
    reader's rules (classify_words_for in sql/classify_words.sql): names,
    acronyms and other non-vocabulary are left out, a spelling of several
    words counts as known if any of them is.
  - record_exposure: one word_events 'exposure' row per word the user is
    learning that an AI app says they read, in its own reply they took in
    whole or in a text they asked for. Learning words only, which the app
    knows from get_vocabulary, so it names a few words rather than resending
    the text (docs/plans/learner-word-data-model.md:
    exposure counts only what the user chose to read or hear, never every
    word an AI wrote).
  - record_seen: the same rows for words the extension saw the user read in
    the reader or in a video's captions, once per word per page or video
    (context.media), however often the client sends them.
  - set_word_status: move words of the user's list between learning and
    known, as the web app's "Move to known" does. Back to learning, the
    userwords trigger gives the word a Langfour card again.
  - add_words: put dictionary words the user asks for into their list as
    learning or known, as the web app's move_words_to_userwords does. Words
    already in the list keep their row, except learning ones asked for as
    known; a known word never goes back to learning here.
  - get_word_exposures: for each learning word, how often the user has seen
    it (exposure rows: read with an AI app, in the reader, in a video's
    captions) and produced it (practice answers where they came up with the
    word themselves, self-reported ones left out), with the dates of the last
    of each.
  - stuck_words: the web app's "Words you likely know": learning words among
    the corpus's most common that were never reviewed, then learning words
    seen in SEEN_VIDEOS videos or more and never looked up, each with the
    videos it was seen in and its look-ups. Suggestions only: move_words
    moves the ones the user ticks through set_status, as set_word_status does.
  - record_lookup: a word_events 'lookup' row each time the extension's
    popup translates a word (/api/translate-word), so "never looked up" means
    something.

The API runs these with the service role on behalf of the OAuth user, so every
query names the user explicitly.
"""

import re
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from practice import PracticeStore
from supabase_client import supabase

Language = Literal["es", "de", "it", "fr"]
SOURCE = "chatgpt"
MAX_TEXT = 20_000
MAX_MEDIA = 500
MAX_SEEN = 2000  # word ids per record_seen call
# Words listed per status in a text's score; the percentages cover all.
LISTED = 40

# Letters only: digits, punctuation and apostrophes split words, so French
# "l'homme" yields "l" (not vocabulary) and "homme".
_WORD = re.compile(r"[^\W\d_]+")

_CLASSIFY_CHUNK = 1000  # tokens per classify_words_for call, as in the extension
_IN_CHUNK = 200
MAX_MISTAKES = 10    # words to revise listed, newest first
_RECALL_SCAN = 1000  # practice answers read to find them
STUCK_TOP = 500      # "common": among the corpus's most frequent words
SEEN_VIDEOS = 10     # seen in this many videos and never looked up: likely known
_PAGE = 1000         # PostgREST's row cap per request


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


class WordMistake(BaseModel):
    word: str
    date: str          # of the wrong answer, YYYY-MM-DD
    note: str | None   # what the user got wrong, from the AI app that recorded it


class Vocabulary(BaseModel):
    language: str | None  # None: no language given and the user has no default
    counts: VocabularyCounts
    words: list[VocabularyWord]
    mistakes: list[WordMistake] = []  # last answer wrong, newest first


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
    recorded: int  # distinct words logged as read or seen
    # record_exposure: words asked for that aren't in the user's learning list
    not_learning: list[str] = []


class SeenRequest(BaseModel):
    source: Literal["reader", "video"]
    # Where it was read: "youtube:<id>" or the page's URL. Words are logged
    # once per media.
    media: str = Field(min_length=1, max_length=MAX_MEDIA)
    # Learning and new words, as the extension classified them.
    word_ids: list[int] = Field(min_length=1, max_length=MAX_SEEN)


class StatusChange(BaseModel):
    changed: list[str]    # now in the requested status, including any already in it
    not_found: list[str]  # not in the user's list in that language, or turned off


class WordsAdded(BaseModel):
    added: list[str]      # now in the user's list in the requested status
    already: list[str]    # in their list already and left as it was
    not_found: list[str]  # not in the dictionary in that language


class WordExposure(BaseModel):
    word: str
    translation: str | None
    seen: int                  # exposure rows, every source
    produced: int              # correct 'produce' answers, self-reported left out
    produce_wrong: int         # wrong 'produce' answers
    last_seen: str | None      # YYYY-MM-DD
    last_produced: str | None  # of the last correct 'produce' answer, YYYY-MM-DD


class WordExposures(BaseModel):
    language: str | None  # None: no language given and the user has no default
    learning: int         # learning words in the language, or among those asked for
    words: list[WordExposure]
    not_learning: list[str] = []  # words asked for that aren't in the user's learning list


class StuckWord(BaseModel):
    word_id: int
    word: str
    translation: str | None
    videos: int   # distinct videos its captions were seen in (exposure rows)
    lookups: int
    # common: among the most common words, never reviewed. seen: in
    # SEEN_VIDEOS videos or more, never looked up.
    reason: Literal["common", "seen"] = "common"


class StuckWords(BaseModel):
    words: list[StuckWord]  # the common ones most common first, then the seen ones most seen first


class MoveRequest(BaseModel):
    word_ids: list[int] = Field(min_length=1, max_length=STUCK_TOP)
    status: Literal["known", "learning"] = "known"


class WordsMoved(BaseModel):
    moved: list[int]  # now in the requested status; words not in the list are left out


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

    def recall_events(self, user_id: str, language: str) -> list[dict]:
        """The user's latest practice answers in a language, newest first."""
        return (self.db.table("word_events")
                .select("word_id, kind, occurred_at, context, words!inner(root, language)")
                .eq("user_id", user_id).eq("source", SOURCE)
                .in_("kind", ["recall_correct", "recall_wrong"])
                .eq("words.language", language)
                .order("occurred_at", desc=True).limit(_RECALL_SCAN).execute().data or [])

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

    def exposed(self, user_id: str, media: str, word_ids: list[int]) -> set[int]:
        """Which of these words already have an exposure logged for this media."""
        out: set[int] = set()
        for chunk in _chunks(word_ids, _IN_CHUNK):
            res = (self.db.table("word_events").select("word_id")
                   .eq("user_id", user_id).eq("kind", "exposure")
                   .eq("context->>media", media).in_("word_id", chunk).execute())
            out |= {r["word_id"] for r in res.data or []}
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

    def resolve_words(self, language: str, words: list[str]) -> dict[str, int]:
        """word as given -> word_id, conjugated or inflected forms included."""
        return PracticeStore(self.db).resolve_words(language, words)

    def default_language(self, user_id: str) -> str | None:
        rows = (self.db.table("userdata").select("default_language")
                .eq("user_id", user_id).limit(1).execute().data or [])
        return rows[0]["default_language"] if rows else None

    def learning_words(self, user_id: str, language: str) -> list[dict]:
        """The user's learning words in a language: [{word_id, root, translation}],
        every page of them."""
        out: list[dict] = []
        start = 0
        while True:
            res = (self.db.table("userwords")
                   .select("word_id, words!inner(root, translation, language)")
                   .eq("user_id", user_id).eq("status", "learning")
                   .eq("words.language", language)
                   .order("word_id").range(start, start + _PAGE - 1).execute())
            rows = res.data or []
            out.extend({"word_id": r["word_id"], "root": r["words"]["root"],
                        "translation": r["words"].get("translation")} for r in rows)
            if len(rows) < _PAGE:
                break
            start += _PAGE
        return out

    def owned(self, user_id: str, word_ids: list[int]) -> set[int]:
        """Which of these words are in the user's list as learning or known."""
        res = (self.db.table("userwords").select("word_id").eq("user_id", user_id)
               .in_("status", ["learning", "known"]).in_("word_id", word_ids).execute())
        return {r["word_id"] for r in res.data or []}

    def set_status(self, user_id: str, word_ids: list[int], status: str) -> None:
        # Not set_userwords_status: it updates auth.uid()'s words, and the API
        # runs as the service role. Rows already in the status are left alone,
        # so the userwords trigger doesn't touch their cards.
        (self.db.table("userwords").update({"status": status})
         .eq("user_id", user_id).in_("word_id", word_ids).neq("status", status).execute())

    def statuses(self, user_id: str, word_ids: list[int]) -> dict[int, str]:
        """word_id -> status for the words in the user's list, turned-off ones included."""
        res = (self.db.table("userwords").select("word_id, status").eq("user_id", user_id)
               .in_("word_id", word_ids).execute())
        return {r["word_id"]: r["status"] for r in res.data or []}

    def add_words(self, user_id: str, word_ids: list[int], status: str,
                  source: str = SOURCE) -> None:
        # As move_words_to_userwords, which works on auth.uid(): a row added
        # meanwhile is kept, and the user's known-words timestamp moves.
        # `source` is where the words came from, as the Practice page filters
        # them: the AI app, or a video's id.
        (self.db.table("userwords")
         .upsert([{"user_id": user_id, "word_id": w, "status": status, "source": source}
                  for w in word_ids], on_conflict="user_id,word_id", ignore_duplicates=True)
         .execute())
        self.touch(user_id)

    def learning_rows(self, user_id: str, word_ids: list[int]) -> list[dict]:
        """The user's learning rows among these words: [{word_id,
        last_reviewed_at, words: {root, translation}}]."""
        out: list[dict] = []
        for chunk in _chunks(word_ids, _IN_CHUNK):
            res = (self.db.table("userwords")
                   .select("word_id, last_reviewed_at, words!inner(root, translation)")
                   .eq("user_id", user_id).eq("status", "learning").in_("word_id", chunk)
                   .execute())
            out.extend(res.data or [])
        return out

    def reviewed(self, user_id: str, word_ids: list[int]) -> set[int]:
        """Which of these words have a review on any card, in Langfour or a
        connected app (srs_reviews)."""
        out: set[int] = set()
        for chunk in _chunks(word_ids, _IN_CHUNK):
            res = (self.db.table("srs_notes")
                   .select("word_id, srs_cards!inner(srs_reviews!inner(card_id))")
                   .eq("user_id", user_id).in_("word_id", chunk).execute())
            out |= {r["word_id"] for r in res.data or []}
        return out

    def events(self, user_id: str, word_ids: list[int], kinds: list[str]) -> list[dict]:
        """The user's word_events of these kinds for these words: [{word_id,
        kind, source, occurred_at, context}], every page of them."""
        out: list[dict] = []
        for chunk in _chunks(word_ids, _IN_CHUNK):
            start = 0
            while True:
                res = (self.db.table("word_events").select("word_id, kind, source, occurred_at, context")
                       .eq("user_id", user_id).in_("kind", kinds).in_("word_id", chunk)
                       .order("id").range(start, start + _PAGE - 1).execute())
                rows = res.data or []
                out.extend(rows)
                if len(rows) < _PAGE:
                    break
                start += _PAGE
        return out

    def touch(self, user_id: str) -> None:
        (self.db.table("userdata").update({"known_words_updated_at": datetime.now(UTC).isoformat()})
         .eq("user_id", user_id).execute())


def get_vocabulary_store() -> VocabularyStore:
    return VocabularyStore(supabase)


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

def get_vocabulary(store: VocabularyStore, user_id: str, language: str | None,
                   status: Literal["due", "learning", "known"], limit: int) -> Vocabulary:
    vocab = Vocabulary.model_validate(store.vocabulary(user_id, language, status, limit))
    if vocab.language:
        vocab.mistakes = _mistakes(store.recall_events(user_id, vocab.language))
    return vocab


def _mistakes(events: list[dict]) -> list[WordMistake]:
    """Words whose newest answer is wrong; a right answer since clears one."""
    latest: dict[int, dict] = {}
    for e in events:  # newest first
        latest.setdefault(e["word_id"], e)
    wrong = [e for e in latest.values() if e["kind"] == "recall_wrong"]
    return [WordMistake(word=e["words"]["root"], date=e["occurred_at"][:10],
                        note=(e.get("context") or {}).get("note"))
            for e in wrong[:MAX_MISTAKES]]


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
                    words: list[str]) -> ExposureSummary:
    asked = list(dict.fromkeys(w.strip() for w in words if w.strip()))
    by_word = _list_words(store, user_id, language, asked)
    ids = sorted(set().union(*by_word.values()))
    statuses = store.statuses(user_id, ids) if ids else {}
    # Of homographs listed under one spelling, only the ones being learned.
    learning = {w for w in ids if statuses.get(w) == "learning"}
    recorded = store.insert_events([
        {"user_id": user_id, "word_id": w, "kind": "exposure", "source": SOURCE}
        for w in sorted(learning)
    ])
    return ExposureSummary(recorded=recorded,
                           not_learning=[w for w in asked if not by_word.get(w, set()) & learning])


def record_seen(store: VocabularyStore, user_id: str, req: SeenRequest) -> ExposureSummary:
    asked = sorted(set(req.word_ids))
    # Words merged away since the extension's dictionary was downloaded are
    # dropped rather than failing the whole batch on the foreign key.
    known_ids = set(store.words(asked))
    fresh = [w for w in asked if w in known_ids]
    logged = store.exposed(user_id, req.media, fresh) if fresh else set()
    recorded = store.insert_events([
        {"user_id": user_id, "word_id": w, "kind": "exposure", "source": req.source,
         "context": {"media": req.media}}
        for w in fresh if w not in logged
    ])
    return ExposureSummary(recorded=recorded)


def _list_words(store: VocabularyStore, user_id: str, language: str,
                asked: list[str]) -> dict[str, set[int]]:
    """word as given -> the ids of the user's learning or known words it names.
    By root first, so every homograph listed under one spelling is found; then
    forms ('encontré' -> encontrar) for the rest."""
    by_word: dict[str, set[int]] = {}
    for r in store.user_words(user_id, language, asked):
        by_word.setdefault(r["root"], set()).add(r["word_id"])
    forms = store.resolve_words(language, [w for w in asked if w not in by_word])
    owned = store.owned(user_id, sorted(set(forms.values()))) if forms else set()
    by_word |= {w: {word_id} for w, word_id in forms.items() if word_id in owned}
    return by_word


def set_word_status(store: VocabularyStore, user_id: str, language: str, words: list[str],
                    status: Literal["known", "learning"]) -> StatusChange:
    asked = list(dict.fromkeys(w.strip() for w in words if w.strip()))
    by_word = _list_words(store, user_id, language, asked)
    ids = set().union(*by_word.values())
    if ids:
        store.set_status(user_id, sorted(ids), status)
    return StatusChange(changed=[w for w in asked if w in by_word],
                        not_found=[w for w in asked if w not in by_word])


def add_words(store: VocabularyStore, user_id: str, language: str, words: list[str],
              status: Literal["known", "learning"]) -> WordsAdded:
    asked = list(dict.fromkeys(w.strip() for w in words if w.strip()))
    ids = store.resolve_words(language, asked)
    current = store.statuses(user_id, sorted(set(ids.values()))) if ids else {}
    new = sorted({w for w in ids.values() if w not in current})
    # The user's word wins over learning, but nothing goes back from known,
    # and turned-off words stay as the RemNote sync left them.
    upgrade = sorted({w for w in ids.values()
                      if status == "known" and current.get(w) == "learning"})
    if new:
        store.add_words(user_id, new, status)
    if upgrade:
        store.set_status(user_id, upgrade, status)
        if not new:
            store.touch(user_id)
    moved = set(new) | set(upgrade)
    return WordsAdded(added=[w for w in asked if ids.get(w) in moved],
                      already=[w for w in asked if w in ids and ids[w] not in moved],
                      not_found=[w for w in asked if w not in ids])


def get_word_exposures(store: VocabularyStore, user_id: str, language: str | None,
                       words: list[str], order: Literal["least", "most"],
                       limit: int) -> WordExposures:
    """How often each learning word was seen and produced: all of the user's
    learning words in the language, or those among `words`."""
    language = language or store.default_language(user_id)
    if not language:
        return WordExposures(language=None, learning=0, words=[])
    learning = {r["word_id"]: r for r in store.learning_words(user_id, language)}
    asked = list(dict.fromkeys(w.strip() for w in words if w.strip()))
    not_learning: list[str] = []
    if asked:
        by_word = _list_words(store, user_id, language, asked)
        picked = set().union(*by_word.values()) & set(learning)
        not_learning = [w for w in asked if not by_word.get(w, set()) & picked]
        learning = {w: r for w, r in learning.items() if w in picked}
    ids = sorted(learning)

    seen: Counter[int] = Counter()
    produced: Counter[int] = Counter()
    produce_wrong: Counter[int] = Counter()
    last_seen: dict[int, str] = {}
    last_produced: dict[int, str] = {}
    for e in store.events(user_id, ids, ["exposure", "recall_correct", "recall_wrong"]) if ids else []:
        w, day = e["word_id"], (e.get("occurred_at") or "")[:10] or None
        context = e.get("context") or {}
        if e["kind"] == "exposure":
            seen[w] += 1
            if day and day > last_seen.get(w, ""):
                last_seen[w] = day
        elif context.get("direction") != "produce":
            continue
        elif e["kind"] == "recall_wrong":
            produce_wrong[w] += 1
        elif not context.get("self_reported"):
            produced[w] += 1
            if day and day > last_produced.get(w, ""):
                last_produced[w] = day

    def key(w: int):
        count = (seen[w], produced[w])
        return (count if order == "least" else (-count[0], -count[1]), learning[w]["root"])

    return WordExposures(language=language, learning=len(ids), not_learning=not_learning, words=[
        WordExposure(word=learning[w]["root"], translation=learning[w].get("translation"),
                     seen=seen[w], produced=produced[w], produce_wrong=produce_wrong[w],
                     last_seen=last_seen.get(w), last_produced=last_produced.get(w))
        for w in sorted(ids, key=key)[:limit]
    ])


def stuck_words(store: VocabularyStore, user_id: str, common: list[int],
                language: str) -> StuckWords:
    """Learning words the user likely knows. First those among `common` (word
    ids, most frequent first) that were never reviewed: imported or saved long
    ago and left. Then any other learning word in the language seen in
    SEEN_VIDEOS videos or more and never looked up, most seen first. Each with
    the videos it was seen in and how often it was looked up, so the user can
    tell which they know."""
    rank = {w: i for i, w in enumerate(common)}
    rows = [r for r in store.learning_rows(user_id, common) if not r.get("last_reviewed_at")]
    reviewed = store.reviewed(user_id, [r["word_id"] for r in rows]) if rows else set()
    rows = sorted((r for r in rows if r["word_id"] not in reviewed), key=lambda r: rank[r["word_id"]])
    learning = {r["word_id"]: r for r in store.learning_words(user_id, language)}
    ids = sorted({r["word_id"] for r in rows} | set(learning))

    videos: dict[int, set[str]] = {}
    lookups: Counter[int] = Counter()
    for e in store.events(user_id, ids, ["exposure", "lookup"]) if ids else []:
        if e["kind"] == "lookup":
            lookups[e["word_id"]] += 1
        elif e["source"] == "video" and (media := (e.get("context") or {}).get("media")):
            videos.setdefault(e["word_id"], set()).add(media)

    listed = {r["word_id"] for r in rows}
    seen = sorted((w for w in learning if w not in listed and not lookups[w]
                   and len(videos.get(w, ())) >= SEEN_VIDEOS),
                  key=lambda w: (-len(videos[w]), learning[w]["root"]))

    return StuckWords(words=[
        StuckWord(word_id=r["word_id"], word=r["words"]["root"],
                  translation=r["words"].get("translation"),
                  videos=len(videos.get(r["word_id"], ())), lookups=lookups[r["word_id"]])
        for r in rows
    ] + [
        StuckWord(word_id=w, word=learning[w]["root"], translation=learning[w].get("translation"),
                  videos=len(videos[w]), lookups=0, reason="seen")
        for w in seen
    ])


def record_lookup(store: VocabularyStore, user_id: str, word_id: int, word: str) -> None:
    """The popup translated `word` (as written on the page) to `word_id`."""
    store.insert_events([{"user_id": user_id, "word_id": word_id, "kind": "lookup",
                          "source": "extension", "context": {"word": word[:MAX_MEDIA]}}])


def move_words(store: VocabularyStore, user_id: str, word_ids: list[int],
               status: Literal["known", "learning"]) -> WordsMoved:
    """set_word_status for words the client names by id. Only learning and
    known words move; one turned off in RemNote stays off."""
    ids = sorted(store.owned(user_id, sorted(set(word_ids))))
    if ids:
        store.set_status(user_id, ids, status)
    return WordsMoved(moved=ids)
