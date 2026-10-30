"""
The grammar the user has worked through, for an AI app connected over MCP
(docs/plans/grammar-tracking.md).

The curriculum is a book: chapters in a fixed order, each holding small
concepts (grammar/README.md). It's read from the YAML files in grammar/, not
from the database. The database (sql/grammar.sql) holds the user's place in
it: which chapters they started or finished, and for every concept they've
practised, when to work it back in.

  - get_overview: one line per chapter with the user's progress, plus the
    teaching guide (grammar/teaching_guide.md) the AI app follows.
  - get_details: the concepts of a few chapters, or a few concepts in full.
  - record: what the user produced and read in a session, and chapters they
    started or finished.

The AI app does the judging (was the sentence right, which concepts did a text
use); this module only stores its verdicts and keeps the refresh dates.

A concept's state: 'not yet' (its chapter isn't started), 'studied' (started,
not learned yet), 'fresh' (learned, refresh date ahead) or 'fading' (refresh
date passed: the AI app should work it back in).

A concept is learned once the user has written MIN_CORRECT sentences that used
it correctly and, for a concept with `forms`, at least half the forms of each
of its verbs (learned_bar() below). Answers to choice and fill-in exercises are
logged as 'recognized' and don't count. A receptive concept is learned when
it's seen in a text, and one the user says they know, at once.

Every mistake is kept: a wrong answer flags its concept with the date and the
AI app's short note, also in chapters the user hasn't reached, until they next
use the concept correctly. The overview lists the flagged concepts to revise,
and up to two chapters worth revisiting (worth_revisiting() below), which the
web app shows too.

The refresh rule (practise() below):
  - once learned: the interval is the concept's base (30, 14 or 7 days for
    easy, medium, hard), and the refresh date that far out;
  - later correct use: the interval doubles (at most 180 days) once half of
    it has passed since it last grew, so using a rule five times in one chat
    counts once;
  - a wrong use halves the interval and brings the concept back tomorrow;
  - seeing a fading concept in a text pushes it out by half the interval;
  - a receptive concept is never drilled, so seeing it counts as practice.
"""

import math
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from supabase_client import supabase

CURRICULUM_DIR = Path(__file__).parent / "grammar"
LEVELS = ("a1", "a2", "b1", "b2", "c1", "c2")
LANGUAGE_NAMES = {"es": "Spanish", "de": "German", "it": "Italian", "fr": "French"}

BASE_INTERVAL = {"easy": 30, "medium": 14, "hard": 7}
MAX_INTERVAL = 180
MIN_CORRECT = 2  # correct sentences before a concept counts as learned

MAX_DETAIL_CHAPTERS = 3
MAX_DETAIL_CONCEPTS = 10
MAX_REVISE = 10  # flagged mistakes the overview lists, newest first

# A chapter worth revisiting (worth_revisiting() below): near the user's place
# in the book, used often, and still slipping on more than one day.
WORTH_WINDOW = 30      # days of events it looks at
WORTH_USE_DAYS = 3     # days the user used the chapter's grammar
WORTH_SLIP_DAYS = 2    # days with a wrong answer in it
WORTH_SETTLED_DAYS = 2  # days of correct use after the last slip that settle it
WORTH_AHEAD = 3        # chapters past the furthest one reached that still count
WORTH_MAX = 2
WORTH_CONCEPT_SLIPS = 2  # wrong answers that mark one of its rules as slipping often

State = Literal["not yet", "studied", "fresh", "fading"]
ChapterStatus = Literal["not started", "started", "done"]
Kind = Literal["seen", "recognized", "produced"]


# ---------------------------------------------------------------------------
# Curriculum
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Concept:
    id: str               # full id: chapter id + "." + the file's local id
    chapter_id: str
    title: str
    scope: str
    difficulty: str = "medium"
    mode: str = "productive"
    variety: str | None = None
    chunk: bool = False
    pitfall: str | None = None
    lemmas: tuple[str, ...] = ()
    later: tuple[str, ...] = ()
    see: tuple[str, ...] = ()
    image: str | None = None  # the web app's picture, in apps/web/public/grammar/<language>/
    # The forms to cover before the concept is learned, by verb: half of each verb's.
    forms: tuple[tuple[str, tuple[str, ...]], ...] = ()
    enclitic: bool = False  # the forms take attached pronouns (hazlo, dímelo)

    @property
    def base_interval(self) -> int:
        return BASE_INTERVAL[self.difficulty]

    @property
    def counts_for_chapter(self) -> bool:
        """Whether the chapter needs it learned to be done: regional and
        receptive concepts don't hold a chapter back."""
        return self.mode == "productive" and self.variety is None


@dataclass(frozen=True)
class Chapter:
    id: str
    level: str
    title: str
    goal: str
    concepts: tuple[Concept, ...]
    continues: str | None = None
    teach: str | None = None


@dataclass(frozen=True)
class Curriculum:
    language: str
    chapters: tuple[Chapter, ...]  # in teaching order
    chapter: dict[str, Chapter] = field(compare=False)
    concept: dict[str, Concept] = field(compare=False)


_CHAPTER_FIELDS = {"id", "title", "goal", "continues", "teach", "concepts"}
_CONCEPT_FIELDS = {"id", "title", "scope", "difficulty", "mode", "variety", "chunk",
                   "lemmas", "pitfall", "later", "see", "image", "forms", "enclitic"}


def _parse_forms(full: str, raw, errors: list[str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict) or not all(
            isinstance(v, list) and v and all(isinstance(f, str) and f for f in v)
            for v in raw.values()):
        errors.append(f"{full}: forms maps each verb to a list of its forms")
        return ()
    return tuple((verb, tuple(unicodedata.normalize("NFC", f.lower()) for f in v))
                 for verb, v in raw.items())


def parse_curriculum(language: str, levels: dict[str, dict]) -> Curriculum:
    """Build a curriculum from the parsed level files, in level order; raises
    ValueError listing every problem found."""
    errors: list[str] = []
    chapters: list[Chapter] = []
    for level, data in levels.items():
        for ch in data.get("chapters") or []:
            cid = ch.get("id", "?")
            if not cid.startswith(f"{language}.") or cid.count(".") != 1:
                errors.append(f"{cid}: chapter ids look like {language}.<slug>")
            if missing := {"id", "title", "goal", "concepts"} - set(ch):
                errors.append(f"{cid}: missing {sorted(missing)}")
            if extra := set(ch) - _CHAPTER_FIELDS:
                errors.append(f"{cid}: unknown fields {sorted(extra)}")
            concepts = []
            for c in ch.get("concepts") or []:
                full = f"{cid}.{c.get('id', '?')}"
                if missing := {"id", "title", "scope"} - set(c):
                    errors.append(f"{full}: missing {sorted(missing)}")
                if extra := set(c) - _CONCEPT_FIELDS:
                    errors.append(f"{full}: unknown fields {sorted(extra)}")
                if c.get("difficulty", "medium") not in BASE_INTERVAL:
                    errors.append(f"{full}: difficulty is easy, medium or hard")
                if c.get("mode", "productive") not in ("productive", "receptive"):
                    errors.append(f"{full}: mode is productive or receptive")
                if c.get("variety") not in (None, "spain", "latam"):
                    errors.append(f"{full}: variety is spain or latam")
                concepts.append(Concept(
                    id=full, chapter_id=cid, title=c.get("title", ""), scope=c.get("scope", ""),
                    difficulty=c.get("difficulty", "medium"), mode=c.get("mode", "productive"),
                    variety=c.get("variety"), chunk=bool(c.get("chunk", False)),
                    pitfall=c.get("pitfall"), lemmas=tuple(c.get("lemmas") or ()),
                    later=tuple(c.get("later") or ()), see=tuple(c.get("see") or ()),
                    image=c.get("image"), forms=_parse_forms(full, c.get("forms"), errors),
                    enclitic=bool(c.get("enclitic", False)),
                ))
            chapters.append(Chapter(
                id=cid, level=level, title=ch.get("title", ""), goal=ch.get("goal", ""),
                concepts=tuple(concepts), continues=ch.get("continues"), teach=ch.get("teach"),
            ))

    position = {}
    for i, ch in enumerate(chapters):
        if ch.id in position:
            errors.append(f"{ch.id}: duplicate chapter")
        position[ch.id] = i
    concept: dict[str, Concept] = {}
    every = [c for ch in chapters for c in ch.concepts]
    for c in every:
        if c.id in concept:
            errors.append(f"{c.id}: duplicate concept")
        concept[c.id] = c
    for c in every:
        for ref in c.later + c.see:
            if ref not in concept:
                errors.append(f"{c.id}: refers to unknown concept {ref}")
        for ref in c.later:
            if ref in concept and position[concept[ref].chapter_id] < position[c.chapter_id]:
                errors.append(f"{c.id}: later points back to {ref}")
    for ch in chapters:
        if ch.continues and position.get(ch.continues, len(chapters)) >= position[ch.id]:
            errors.append(f"{ch.id}: continues {ch.continues}, which isn't an earlier chapter")
    if errors:
        raise ValueError(f"{language} grammar curriculum:\n" + "\n".join(errors))
    return Curriculum(language=language, chapters=tuple(chapters),
                      chapter={ch.id: ch for ch in chapters}, concept=concept)


@cache
def load_curriculum(language: str) -> Curriculum | None:
    """The curriculum in grammar/<language>/, or None if there is none."""
    folder = CURRICULUM_DIR / language
    files = [(lvl, folder / f"{lvl}.yaml") for lvl in LEVELS]
    levels = {lvl: yaml.safe_load(path.read_text()) for lvl, path in files if path.exists()}
    return parse_curriculum(language, levels) if levels else None


@cache
def teaching_guide() -> str:
    return (CURRICULUM_DIR / "teaching_guide.md").read_text()


@dataclass(frozen=True)
class Copy:
    title: str
    description: str


@cache
def load_ui_copy(language: str) -> dict[str, Copy] | None:
    """The learner-facing titles and one-line descriptions in
    grammar/<language>/ui/, by chapter and full concept id; None if there are
    none. They must cover the curriculum exactly, so a new or renamed id fails
    the tests until it has copy."""
    cur = load_curriculum(language)
    folder = CURRICULUM_DIR / language / "ui"
    files = [folder / f"{lvl}.yaml" for lvl in LEVELS if (folder / f"{lvl}.yaml").exists()]
    if cur is None or not files:
        return None
    copy: dict[str, Copy] = {}
    for path in files:
        for ch in yaml.safe_load(path.read_text()).get("chapters") or []:
            copy[ch["id"]] = Copy(ch["title"], ch["description"])
            for c in ch.get("concepts") or []:
                copy[f"{ch['id']}.{c['id']}"] = Copy(c["title"], c["description"])
    ids = set(cur.chapter) | set(cur.concept)
    if missing := sorted(ids - set(copy)):
        raise ValueError(f"{language} grammar UI copy is missing {missing}")
    if extra := sorted(set(copy) - ids):
        raise ValueError(f"{language} grammar UI copy has ids the curriculum doesn't: {extra}")
    return copy


def _ui_copy(cur: Curriculum):
    """Learner-facing copy for an id, falling back to the curriculum's own
    title and goal or scope where a language has no UI files."""
    copy = load_ui_copy(cur.language)

    def get(i: str) -> Copy:
        if copy:
            return copy[i]
        item = cur.chapter.get(i) or cur.concept[i]
        return Copy(item.title, item.goal if i in cur.chapter else item.scope)
    return get


# ---------------------------------------------------------------------------
# The refresh rule
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Progress:
    """A user_grammar_concepts row."""
    first_correct_at: datetime | None = None
    learned_at: datetime | None = None  # when it first met the bar; null while studied
    last_seen_at: datetime | None = None
    last_produced_at: datetime | None = None
    interval_days: int | None = None
    interval_grown_at: datetime | None = None
    refresh_at: datetime | None = None
    produced_count: int = 0
    error_count: int = 0
    correct_count: int = 0                 # correct sentences, self-reports not included
    forms_produced: tuple[str, ...] = ()   # the concept's forms used correctly, sorted
    mistake_at: datetime | None = None     # the last mistake, until the next correct use
    mistake_note: str | None = None

    _TIMES = ("first_correct_at", "learned_at", "last_seen_at", "last_produced_at",
              "interval_grown_at", "refresh_at", "mistake_at")

    @classmethod
    def from_row(cls, row: dict) -> "Progress":
        times = {k: datetime.fromisoformat(row[k]) if row.get(k) else None for k in cls._TIMES}
        return cls(**times, interval_days=row.get("interval_days"),
                   produced_count=row.get("produced_count") or 0,
                   error_count=row.get("error_count") or 0,
                   correct_count=row.get("correct_count") or 0,
                   forms_produced=tuple(row.get("forms_produced") or ()),
                   mistake_note=row.get("mistake_note"))

    def to_row(self) -> dict:
        row = {k: (getattr(self, k).isoformat() if getattr(self, k) else None)
               for k in self._TIMES}
        return row | {"interval_days": self.interval_days,
                      "produced_count": self.produced_count, "error_count": self.error_count,
                      "correct_count": self.correct_count,
                      "forms_produced": list(self.forms_produced),
                      "mistake_note": self.mistake_note}

    @property
    def mistake(self) -> str | None:
        """The flagged mistake for the AI app: its date and note."""
        if not self.mistake_at:
            return None
        return f"{self.mistake_at.date().isoformat()}: {self.mistake_note or 'no note'}"



def state(progress: Progress | None, chapter_status: ChapterStatus, now: datetime) -> State:
    if progress and progress.learned_at:
        return "fading" if progress.refresh_at <= now else "fresh"
    return "studied" if chapter_status != "not started" else "not yet"


_CLITICS = re.compile(r"(?:me|te|se|lo|la|le|los|las|les|nos|os)+")


def _plain(word: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", word)
                   if unicodedata.category(ch) != "Mn")


def forms_in(sentence: str | None, concept: Concept) -> set[str]:
    """The concept's forms that occur in a sentence, as whole words, accents
    included. For an enclitic concept a form may carry attached pronouns, which
    can add an accent (hazlo has haz, dímelo di)."""
    if not sentence or not concept.forms:
        return set()
    words = set(re.findall(r"[^\W\d_]+", unicodedata.normalize("NFC", sentence.lower())))
    plain = {_plain(w) for w in words}
    found = set()
    for _, forms in concept.forms:
        for f in forms:
            stem = _plain(f)
            if f in words or (concept.enclitic and any(
                    w.startswith(stem) and _CLITICS.fullmatch(w[len(stem):]) for w in plain)):
                found.add(f)
    return found


def to_learn(p: Progress | None, concept: Concept) -> str | None:
    """What the user still has to do before the concept is learned, in a
    sentence for the AI app; None once it is."""
    p = p or Progress()
    if p.learned_at:
        return None
    if concept.mode == "receptive":
        return "Use it in a text the user reads."
    parts = []
    if (more := MIN_CORRECT - p.correct_count) > 0:
        parts.append(f"{more} more correct sentence{'s' * (more > 1)} written by the user")
    done = set(p.forms_produced)
    for verb, forms in concept.forms:
        more = math.ceil(len(forms) / 2) - len(done & set(forms))
        if more > 0:
            left = ", ".join(f for f in forms if f not in done)
            parts.append(f"{verb}: {more} more of {left}")
    return "; ".join(parts) + "." if parts else None


def practise(p: Progress, concept: Concept, kind: Kind, correct: bool | None, now: datetime,
             forms: set[str] = frozenset(), self_reported: bool = False,
             note: str | None = None) -> Progress:
    """The progress after one result; see the module docstring for the rule."""
    if correct is False:
        p = replace(p, mistake_at=now, mistake_note=note)
    if kind == "recognized":
        return p  # choosing a form isn't using it; only a wrong choice is kept
    if kind == "produced":
        p = replace(p, last_produced_at=now, produced_count=p.produced_count + 1,
                    error_count=p.error_count + (0 if correct else 1))
        if correct and not self_reported:
            p = replace(p, first_correct_at=p.first_correct_at or now,
                        correct_count=p.correct_count + 1,
                        forms_produced=tuple(sorted(set(p.forms_produced) | forms)),
                        mistake_at=None, mistake_note=None)
    else:
        p = replace(p, last_seen_at=now)

    if p.learned_at is None:
        receptive_seen = kind == "seen" and concept.mode == "receptive"
        if receptive_seen or (correct and (self_reported or to_learn(p, concept) is None)):
            return replace(p, learned_at=now, interval_days=concept.base_interval,
                           interval_grown_at=now,
                           refresh_at=now + timedelta(days=concept.base_interval))
        return p  # not learned yet: nothing to refresh

    if correct or (kind == "seen" and concept.mode == "receptive"):
        if now - p.interval_grown_at >= timedelta(days=p.interval_days / 2):
            p = replace(p, interval_days=min(2 * p.interval_days, MAX_INTERVAL),
                        interval_grown_at=now)
        else:
            return p  # too soon: keep the refresh date, including tomorrow after an error
        out = now + timedelta(days=p.interval_days)
        return replace(p, refresh_at=max(p.refresh_at or out, out))

    if kind == "produced":  # wrong
        return replace(p, interval_days=max(1, p.interval_days // 2), interval_grown_at=now,
                       refresh_at=now + timedelta(days=1))
    if p.refresh_at <= now:  # seen while fading
        return replace(p, refresh_at=now + timedelta(days=p.interval_days / 2))
    return p


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

class GrammarOverview(BaseModel):
    language: str | None
    overview: str  # one line per chapter
    guide: str     # how to teach from the curriculum; empty without one


class ConceptRef(BaseModel):
    id: str
    title: str


class ConceptSummary(BaseModel):
    id: str
    title: str
    scope: str
    state: State
    mode: Literal["productive", "receptive"]
    variety: Literal["spain", "latam"] | None
    chunk: bool
    to_learn: str | None  # what's left before it counts as learned; None once it is
    mistake: str | None   # the flagged mistake to revise: its date and note


class ConceptDetail(ConceptSummary):
    chapter: str
    difficulty: Literal["easy", "medium", "hard"]
    pitfall: str | None
    later: list[ConceptRef]  # refinements that come in later chapters
    see: list[ConceptRef]
    forms: dict[str, list[str]]  # by verb: the forms to cover, half of each verb's
    forms_produced: list[str]    # of those, the ones the user has used correctly
    correct_sentences: int
    refresh_at: str | None


class ChapterDetail(BaseModel):
    id: str
    level: str
    title: str
    goal: str
    teach: str | None
    status: ChapterStatus
    concepts: list[ConceptSummary]


class GrammarDetails(BaseModel):
    chapters: list[ChapterDetail]
    concepts: list[ConceptDetail]
    not_found: list[str]


class GrammarResult(BaseModel):
    concept: str = Field(..., min_length=1, max_length=120,
                         description="A concept id, e.g. 'es.ser_estar_1.characteristic_vs_state'")
    kind: Kind = Field(
        ..., description="'produced': one sentence the user wrote or said in full that needed "
                         "the concept. 'recognized': one answer to a choice or fill-in exercise. "
                         "'seen': you used it on purpose in a text the user read.")
    correct: bool | None = Field(
        None, description="For 'produced' and 'recognized': whether the user got this "
                          "concept right in that sentence or answer.")
    self_reported: bool = Field(
        False, description="Only when the user told you in their own words that they already "
                           "know the concept, with no exercise. Never for exercise answers.")
    sentence: str | None = Field(
        None, max_length=300,
        description="For 'produced': the user's whole sentence, exactly as they wrote it.")
    note: str | None = Field(
        None, max_length=200,
        description="For a wrong result: a short note for whoever revises it later, saying "
                    "what the user wrote and what was right, e.g. 'lo for la factura: the "
                    "pronoun agrees with the feminine noun'.")

    @model_validator(mode="after")
    def _check(self):
        if (self.kind != "seen") != (self.correct is not None):
            raise ValueError("correct is required for 'produced' and 'recognized', and only for them")
        if self.self_reported and not (self.kind == "produced" and self.correct):
            raise ValueError("self_reported is for a correct 'produced' result only")
        if self.kind == "produced" and not self.self_reported and not self.sentence:
            raise ValueError("a 'produced' result needs the user's sentence")
        if self.note and self.correct is not False:
            raise ValueError("note is for a wrong result only")
        return self


class ChapterUpdate(BaseModel):
    chapter: str = Field(..., min_length=1, max_length=80, description="A chapter id, e.g. 'es.ser'")
    status: Literal["started", "done"]
    self_reported: bool = Field(
        False, description="For 'done': the user told you they already know the chapter. "
                           "Without it, 'done' needs every concept of the chapter learned.")


class ConceptChange(BaseModel):
    concept: str
    before: State
    after: State


class GrammarRecord(BaseModel):
    recorded: int                # results logged as events
    changed: list[ConceptChange]  # concepts whose state moved
    to_learn: dict[str, str]     # concepts practised but not learned yet, and what's left
    chapters: list[str]          # chapters whose status changed
    not_done: list[str]          # chapters asked to be done with concepts still to learn
    not_found: list[str]         # ids not in the curriculum, so not recorded


class BookConcept(BaseModel):
    id: str
    title: str
    state: State


class BookChapter(BaseModel):
    id: str
    number: int  # its place in the book, from 1
    level: str
    title: str
    description: str
    status: ChapterStatus
    concepts: list[BookConcept]


class WorthRevisiting(BaseModel):
    chapter: str
    concepts: list[str]  # its rules that slip often, in chapter order; may be empty


class GrammarBook(BaseModel):
    """The web app's table of contents; no chapters without a curriculum."""
    language: str
    chapters: list[BookChapter]
    worth_revisiting: list[WorthRevisiting] = []  # best first (worth_revisiting())


class ChapterRef(BaseModel):
    id: str
    number: int
    title: str


class LessonRef(BaseModel):
    """A concept in another chapter, with where to find it."""
    id: str
    title: str
    chapter: ChapterRef


class LessonConcept(BaseModel):
    id: str
    title: str
    description: str
    image: str | None
    state: State
    difficulty: Literal["easy", "medium", "hard"]
    mode: Literal["productive", "receptive"]
    variety: Literal["spain", "latam"] | None
    chunk: bool
    pitfall: str | None
    later: list[LessonRef]
    see: list[LessonRef]
    used: int      # times the user produced it
    mistakes: int  # of those, wrong
    last_used_at: str | None
    refresh_at: str | None


class Lesson(BaseModel):
    """One chapter in full, for the web app's lesson page."""
    id: str
    number: int
    level: str
    title: str
    description: str
    status: ChapterStatus
    started_at: str | None
    finished_at: str | None
    continues: ChapterRef | None
    previous: ChapterRef | None
    next: ChapterRef | None
    concepts: list[LessonConcept]


# ---------------------------------------------------------------------------
# Storage. Like vocabulary.VocabularyStore: everything that touches Supabase is
# here, so the logic below runs against an in-memory stand-in in tests. The
# API runs as the service role on behalf of the OAuth user, so every query
# names the user.
# ---------------------------------------------------------------------------

class GrammarStore:
    def __init__(self, client):
        self.db = client

    def default_language(self, user_id: str) -> str | None:
        rows = (self.db.table("userdata").select("default_language")
                .eq("user_id", user_id).execute().data)
        return rows[0]["default_language"] if rows else None

    def chapters(self, user_id: str) -> list[dict]:
        return (self.db.table("user_grammar_chapters").select("*")
                .eq("user_id", user_id).execute().data or [])

    def concepts(self, user_id: str) -> list[dict]:
        return (self.db.table("user_grammar_concepts").select("*")
                .eq("user_id", user_id).execute().data or [])

    def events(self, user_id: str, since: datetime) -> list[dict]:
        """The user's exercise and sentence results since a time, oldest first."""
        rows, start, page = [], 0, 1000
        while True:
            batch = (self.db.table("grammar_events")
                     .select("concept_id, kind, correct, self_reported, occurred_at")
                     .eq("user_id", user_id).in_("kind", ["produced", "recognized"])
                     .gte("occurred_at", since.isoformat()).order("occurred_at")
                     .range(start, start + page - 1).execute().data or [])
            rows += batch
            if len(batch) < page:
                return rows
            start += page

    def record(self, user_id: str, events: list[dict], concepts: list[dict],
               chapters: list[dict]) -> int:
        """Write atomically; -1 means a previous-row check failed, with nothing written."""
        return self.db.rpc("record_grammar", {
            "p_user_id": user_id, "p_events": events,
            "p_concepts": concepts, "p_chapters": chapters,
        }).execute().data


def get_grammar_store() -> GrammarStore:
    return GrammarStore(supabase)


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(UTC)


def _language(store: GrammarStore, user_id: str, language: str | None) -> str | None:
    return language or store.default_language(user_id)


def _require(language: str | None) -> Curriculum:
    cur = load_curriculum(language) if language else None
    if cur is None:
        name = LANGUAGE_NAMES.get(language or "", language or "this language")
        raise ValueError(f"Langfour has no grammar curriculum for {name} yet; only Spanish so far.")
    return cur


def _user_state(store: GrammarStore, user_id: str, cur: Curriculum
                ) -> tuple[dict[str, dict], dict[str, Progress]]:
    chapters = {r["chapter_id"]: r for r in store.chapters(user_id) if r["chapter_id"] in cur.chapter}
    progress = {r["concept_id"]: Progress.from_row(r) for r in store.concepts(user_id)
                if r["concept_id"] in cur.concept}
    return chapters, progress


def _status(chapters: dict[str, dict], chapter_id: str) -> ChapterStatus:
    row = chapters.get(chapter_id)
    return row["status"] if row else "not started"


def worth_revisiting(cur: Curriculum, chapters: dict[str, dict], progress: dict[str, Progress],
                     events: list[dict], now: datetime) -> list[WorthRevisiting]:
    """The chapters worth a friendly nudge, best first: at most WORTH_MAX.

    A chapter qualifies when it's near the user's place in the book (its level
    or the one below that of the furthest chapter reached, and no more than
    WORTH_AHEAD chapters past it), the user used its grammar on WORTH_USE_DAYS
    days of the last WORTH_WINDOW, and got it wrong on WORTH_SLIP_DAYS of them.
    Slips on one day are just learning it; slips on several mean it isn't
    settling. Using it correctly on WORTH_SETTLED_DAYS later days settles it.
    With each chapter come its rules that slip often: wrong WORTH_CONCEPT_SLIPS
    times in the window and not settled the same way."""
    reached = [i for i, ch in enumerate(cur.chapters)
               if _status(chapters, ch.id) != "not started"
               or any(progress.get(c.id) and progress[c.id].learned_at for c in ch.concepts)]
    if not reached:
        return []
    frontier = cur.chapters[reached[-1]]
    lowest = max(0, LEVELS.index(frontier.level) - 1)
    position = {ch.id: i for i, ch in enumerate(cur.chapters)}

    # By chapter and by concept: the days used, and the times wrong and right.
    used: dict[str, set] = {}
    slips: dict[str, list[datetime]] = {}
    correct: dict[str, list[datetime]] = {}
    since = now - timedelta(days=WORTH_WINDOW)
    for e in events:
        c = cur.concept.get(e["concept_id"])
        at = datetime.fromisoformat(e["occurred_at"])
        if c is None or e["kind"] == "seen" or e.get("self_reported") or at < since:
            continue
        used.setdefault(c.chapter_id, set()).add(at.date())
        for key in (c.chapter_id, c.id):
            (slips if e["correct"] is False else correct).setdefault(key, []).append(at)

    def settled(key: str) -> bool:
        last = max(t.date() for t in slips[key])
        return len({t.date() for t in correct.get(key, []) if t.date() > last}) >= WORTH_SETTLED_DAYS

    ranked = []
    for chapter_id, days in used.items():
        ch = cur.chapter[chapter_id]
        if (LEVELS.index(ch.level) < lowest or position[chapter_id] > reached[-1] + WORTH_AHEAD
                or len(days) < WORTH_USE_DAYS):
            continue
        slip_days = {t.date() for t in slips.get(chapter_id, [])}
        if len(slip_days) < WORTH_SLIP_DAYS:
            continue
        if settled(chapter_id):
            continue
        ranked.append((len(slip_days), max(slip_days), chapter_id))
    return [WorthRevisiting(chapter=i, concepts=[
                c.id for c in cur.chapter[i].concepts
                if len(slips.get(c.id, [])) >= WORTH_CONCEPT_SLIPS and not settled(c.id)])
            for *_, i in sorted(ranked, reverse=True)[:WORTH_MAX]]


def _worth_revisiting(store: GrammarStore, user_id: str, cur: Curriculum,
                      chapters: dict[str, dict], progress: dict[str, Progress],
                      now: datetime) -> list[WorthRevisiting]:
    events = store.events(user_id, now - timedelta(days=WORTH_WINDOW))
    return worth_revisiting(cur, chapters, progress, events, now)


def get_overview(store: GrammarStore, user_id: str, language: str | None,
                 now: datetime | None = None) -> GrammarOverview:
    now = now or _now()
    language = _language(store, user_id, language)
    cur = load_curriculum(language) if language else None
    if cur is None:
        return GrammarOverview(language=language, guide="", overview=(
            f"Langfour has no grammar curriculum for "
            f"{LANGUAGE_NAMES.get(language or '', language or 'this language')} yet; "
            f"only Spanish so far."))

    chapters, progress = _user_state(store, user_id, cur)
    mark = {"done": "✓", "started": "→", "not started": "·"}
    lines, level, fading_total = [], None, 0
    flagged = sorted(((p.mistake_at, i) for i, p in progress.items() if p.mistake_at), reverse=True)
    for ch in cur.chapters:
        if ch.level != level:
            level = ch.level
            lines += ["", level.upper()]
        status = _status(chapters, ch.id)
        states = [state(progress.get(c.id), status, now) for c in ch.concepts]
        learned = sum(s in ("fresh", "fading") for s in states)
        fading = states.count("fading")
        fading_total += fading
        line = f"{mark[status]} {ch.id}  {ch.title}"
        if status != "not started" or learned:
            line += f"  {learned}/{len(states)} learned"
            if fading:
                line += f", {fading} fading"
        lines.append(line)

    started = [c for c in cur.chapters if _status(chapters, c.id) == "started"]
    done = sum(_status(chapters, c.id) == "done" for c in cur.chapters)
    levels = f"{cur.chapters[0].level.upper()}–{cur.chapters[-1].level.upper()}"
    head = [
        f"{LANGUAGE_NAMES.get(language, language)} grammar, {levels}, "
        f"{len(cur.chapters)} chapters in teaching order. "
        f"Started: {', '.join(c.id for c in started) or 'none'}. Done: {done}. "
        f"Fading concepts: {fading_total}. Mistakes to revise: {len(flagged)}.",
        "Key: ✓ done, → started, · not started. 'learned' counts concepts that met the bar "
        "(the guide's 'When a concept is learned'); fading ones are due to be worked back in. "
        "get_grammar_details lists a chapter's concepts and what each still needs.",
    ]
    if worth := _worth_revisiting(store, user_id, cur, chapters, progress, now):
        named = [w.chapter + (f" (slips most: {', '.join(w.concepts)})" if w.concepts else "")
                 for w in worth]
        head.append(f"Worth revisiting: {'; '.join(named)} (the guide's 'Chapters worth revisiting').")
    if flagged:
        head += ["", "TO REVISE (the user's mistakes, newest first; the guide's 'Revising mistakes')"]
        for _, i in flagged[:MAX_REVISE]:
            c = cur.concept[i]
            reached = "" if _status(chapters, c.chapter_id) != "not started" else "  (chapter not started)"
            head.append(f"{i}  {progress[i].mistake}{reached}")
    return GrammarOverview(language=language, overview="\n".join(head + lines),
                           guide=teaching_guide())


def _summary(c: Concept, s: State, p: Progress | None) -> dict:
    return {"id": c.id, "title": c.title, "scope": c.scope, "state": s,
            "mode": c.mode, "variety": c.variety, "chunk": c.chunk,
            "to_learn": to_learn(p, c) if s != "not yet" else None,
            "mistake": p.mistake if p else None}


def get_details(store: GrammarStore, user_id: str, language: str | None,
                chapter_ids: list[str], concept_ids: list[str],
                now: datetime | None = None) -> GrammarDetails:
    now = now or _now()
    cur = _require(_language(store, user_id, language))
    chapters, progress = _user_state(store, user_id, cur)

    def concept_state(c: Concept) -> State:
        return state(progress.get(c.id), _status(chapters, c.chapter_id), now)

    def ref(i: str) -> ConceptRef:
        return ConceptRef(id=i, title=cur.concept[i].title)

    asked_chapters = list(dict.fromkeys(chapter_ids))[:MAX_DETAIL_CHAPTERS]
    asked_concepts = list(dict.fromkeys(concept_ids))[:MAX_DETAIL_CONCEPTS]
    out_chapters = [
        ChapterDetail(id=ch.id, level=ch.level, title=ch.title, goal=ch.goal, teach=ch.teach,
                      status=_status(chapters, ch.id),
                      concepts=[ConceptSummary(**_summary(c, concept_state(c), progress.get(c.id)))
                                for c in ch.concepts])
        for ch in (cur.chapter[i] for i in asked_chapters if i in cur.chapter)
    ]
    out_concepts = [
        ConceptDetail(**_summary(c, concept_state(c), p := progress.get(c.id)),
                      chapter=c.chapter_id, difficulty=c.difficulty, pitfall=c.pitfall,
                      later=[ref(i) for i in c.later], see=[ref(i) for i in c.see],
                      forms={verb: list(forms) for verb, forms in c.forms},
                      forms_produced=list(p.forms_produced) if p else [],
                      correct_sentences=p.correct_count if p else 0,
                      refresh_at=p.refresh_at.isoformat() if p and p.learned_at else None)
        for c in (cur.concept[i] for i in asked_concepts if i in cur.concept)
    ]
    not_found = ([i for i in asked_chapters if i not in cur.chapter]
                 + [i for i in asked_concepts if i not in cur.concept])
    return GrammarDetails(chapters=out_chapters, concepts=out_concepts, not_found=not_found)


def record(store: GrammarStore, user_id: str, language: str, results: list[GrammarResult],
           chapter_updates: list[ChapterUpdate], now: datetime | None = None) -> GrammarRecord:
    for _ in range(3):
        saved = _record_once(store, user_id, language, results, chapter_updates, now or _now())
        if saved is not None:
            return saved
    raise RuntimeError("Grammar progress changed during recording; please try again.")


def _record_once(store: GrammarStore, user_id: str, language: str, results: list[GrammarResult],
                 chapter_updates: list[ChapterUpdate], now: datetime) -> GrammarRecord | None:
    cur = _require(language)
    chapters, progress = _user_state(store, user_id, cur)
    old_status = {i: _status(chapters, i) for i in cur.chapter}
    not_found = []
    changed_chapters: dict[str, dict] = {}

    def set_chapter(chapter_id: str, status: str) -> None:
        row = changed_chapters.get(chapter_id) or chapters.get(chapter_id)
        if status == "started":
            if row:  # already started or done; starting again changes nothing
                return
            new = {"chapter_id": chapter_id, "status": "started",
                   "started_at": now.isoformat(), "finished_at": None}
        else:
            if row and row["status"] == "done":
                return
            new = {"chapter_id": chapter_id, "status": "done",
                   "started_at": row["started_at"] if row else now.isoformat(),
                   "finished_at": now.isoformat()}
        changed_chapters[chapter_id] = new

    for u in chapter_updates:
        if u.chapter not in cur.chapter:
            not_found.append(u.chapter)
        elif u.status == "started" or u.self_reported:
            set_chapter(u.chapter, u.status)

    events, before, touched, counted = [], {}, {}, set()
    # Results summarize a session, not a timeline. Apply exposure first so a
    # production error wins even when a receptive concept was also seen.
    for r in sorted(results, key=lambda r: r.kind == "produced"):
        c = cur.concept.get(r.concept)
        if c is None:
            not_found.append(r.concept)
            continue
        if r.kind == "produced" and r.sentence:
            key = (c.id, " ".join(r.sentence.lower().split()))
            if key in counted:  # the same sentence twice counts once
                continue
            counted.add(key)
        before.setdefault(c.id, state(progress.get(c.id), old_status[c.chapter_id], now))
        if r.kind == "produced" and r.correct:
            # Using a concept means its chapter is open, whatever the app said. A
            # mistake in grammar the user hasn't reached is only kept for later.
            set_chapter(c.chapter_id, "started")
        touched[c.id] = practise(touched.get(c.id) or progress.get(c.id) or Progress(),
                                 c, r.kind, r.correct, now, forms_in(r.sentence, c),
                                 r.self_reported, r.note)
        events.append({"concept_id": c.id, "kind": r.kind, "correct": r.correct,
                       "self_reported": r.self_reported, "sentence": r.sentence,
                       "note": r.note})

    # A chapter is done once every concept that counts is learned, or the user says so.
    not_done = []
    for u in chapter_updates:
        if (u.chapter in cur.chapter and u.status == "done" and not u.self_reported
                and old_status[u.chapter] != "done"):
            left = [c for c in cur.chapter[u.chapter].concepts if c.counts_for_chapter
                    and not (touched.get(c.id) or progress.get(c.id) or Progress()).learned_at]
            if left:
                not_done.append(u.chapter)
            else:
                set_chapter(u.chapter, "done")

    new_status = old_status | {i: row["status"] for i, row in changed_chapters.items()}
    recorded = store.record(
        user_id, events,
        [{"concept_id": i, **p.to_row(),
          "previous": {"concept_id": i, **progress[i].to_row()} if i in progress else None}
         for i, p in touched.items()],
        [{**row, "previous": chapters.get(i)} for i, row in changed_chapters.items()],
    ) if events or changed_chapters else 0
    if recorded == -1:  # another request committed since our read; no writes were made
        return None

    after = {i: state(touched[i], new_status[cur.concept[i].chapter_id], now) for i in touched}
    return GrammarRecord(
        recorded=recorded,
        changed=[ConceptChange(concept=i, before=before[i], after=after[i])
                 for i in after if before[i] != after[i]],
        to_learn={i: left for i in touched if (left := to_learn(touched[i], cur.concept[i]))},
        chapters=[i for i in changed_chapters if new_status[i] != old_status[i]],
        not_done=list(dict.fromkeys(not_done)),
        not_found=list(dict.fromkeys(not_found)),
    )


# ---------------------------------------------------------------------------
# The web app's grammar book: the same curriculum and progress as the MCP
# tools, as structured data for the table of contents and a lesson page.
# ---------------------------------------------------------------------------

def get_book(store: GrammarStore, user_id: str, language: str,
             now: datetime | None = None) -> GrammarBook:
    now = now or _now()
    cur = load_curriculum(language)
    if cur is None:
        return GrammarBook(language=language, chapters=[])
    chapters, progress = _user_state(store, user_id, cur)
    copy = _ui_copy(cur)
    out = []
    for n, ch in enumerate(cur.chapters, 1):
        status = _status(chapters, ch.id)
        out.append(BookChapter(
            id=ch.id, number=n, level=ch.level, title=copy(ch.id).title,
            description=copy(ch.id).description, status=status,
            concepts=[BookConcept(id=c.id, title=copy(c.id).title,
                                  state=state(progress.get(c.id), status, now))
                      for c in ch.concepts]))
    return GrammarBook(language=language, chapters=out,
                       worth_revisiting=_worth_revisiting(store, user_id, cur, chapters, progress, now))


def get_lesson(store: GrammarStore, user_id: str, language: str, chapter_id: str,
               now: datetime | None = None) -> Lesson:
    """Raises LookupError for a chapter the curriculum doesn't have."""
    now = now or _now()
    cur = _require(language)
    if chapter_id not in cur.chapter:
        raise LookupError(f"No grammar chapter {chapter_id}")
    chapters, progress = _user_state(store, user_id, cur)
    number = {c.id: n for n, c in enumerate(cur.chapters, 1)}
    copy = _ui_copy(cur)

    def chapter_ref(i: str | None) -> ChapterRef | None:
        return ChapterRef(id=i, number=number[i], title=copy(i).title) if i else None

    def ref(i: str) -> LessonRef:
        return LessonRef(id=i, title=copy(i).title, chapter=chapter_ref(cur.concept[i].chapter_id))

    def iso(t: datetime | None) -> str | None:
        return t.isoformat() if t else None

    ch = cur.chapter[chapter_id]
    n = number[ch.id]
    status = _status(chapters, ch.id)
    row = chapters.get(ch.id) or {}
    concepts = []
    for c in ch.concepts:
        p = progress.get(c.id) or Progress()
        concepts.append(LessonConcept(
            id=c.id, title=copy(c.id).title, description=copy(c.id).description, image=c.image,
            state=state(progress.get(c.id), status, now), difficulty=c.difficulty, mode=c.mode,
            variety=c.variety, chunk=c.chunk, pitfall=c.pitfall,
            later=[ref(i) for i in c.later], see=[ref(i) for i in c.see],
            used=p.produced_count, mistakes=p.error_count,
            last_used_at=iso(p.last_produced_at),
            refresh_at=iso(p.refresh_at) if p.learned_at else None))
    return Lesson(
        id=ch.id, number=n, level=ch.level, title=copy(ch.id).title,
        description=copy(ch.id).description, status=status,
        started_at=row.get("started_at"), finished_at=row.get("finished_at"),
        continues=chapter_ref(ch.continues),
        previous=chapter_ref(cur.chapters[n - 2].id) if n > 1 else None,
        next=chapter_ref(cur.chapters[n].id) if n < len(cur.chapters) else None,
        concepts=concepts)

