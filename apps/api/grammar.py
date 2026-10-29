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
never used correctly), 'fresh' (used correctly, refresh date ahead) or
'fading' (refresh date passed: the AI app should work it back in).

The refresh rule (practise() below):
  - first correct use: the interval is the concept's base (30, 14 or 7 days
    for easy, medium, hard), and the refresh date that far out;
  - later correct use: the interval doubles (at most 180 days) once half of
    it has passed since it last grew, so using a rule five times in one chat
    counts once;
  - a wrong use halves the interval and brings the concept back tomorrow;
  - seeing a fading concept in a text pushes it out by half the interval;
  - a receptive concept is never drilled, so seeing it counts as practice.
"""

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

MAX_DETAIL_CHAPTERS = 3
MAX_DETAIL_CONCEPTS = 10

State = Literal["not yet", "studied", "fresh", "fading"]
ChapterStatus = Literal["not started", "started", "done"]


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

    @property
    def base_interval(self) -> int:
        return BASE_INTERVAL[self.difficulty]


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
                   "lemmas", "pitfall", "later", "see"}


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


# ---------------------------------------------------------------------------
# The refresh rule
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Progress:
    """A user_grammar_concepts row."""
    first_correct_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_produced_at: datetime | None = None
    interval_days: int | None = None
    interval_grown_at: datetime | None = None
    refresh_at: datetime | None = None
    produced_count: int = 0
    error_count: int = 0

    _TIMES = ("first_correct_at", "last_seen_at", "last_produced_at",
              "interval_grown_at", "refresh_at")

    @classmethod
    def from_row(cls, row: dict) -> "Progress":
        times = {k: datetime.fromisoformat(row[k]) if row.get(k) else None for k in cls._TIMES}
        return cls(**times, interval_days=row.get("interval_days"),
                   produced_count=row.get("produced_count") or 0,
                   error_count=row.get("error_count") or 0)

    def to_row(self) -> dict:
        row = {k: (getattr(self, k).isoformat() if getattr(self, k) else None)
               for k in self._TIMES}
        return row | {"interval_days": self.interval_days,
                      "produced_count": self.produced_count, "error_count": self.error_count}


def state(progress: Progress | None, chapter_status: ChapterStatus, now: datetime) -> State:
    if progress and progress.first_correct_at:
        return "fading" if progress.refresh_at <= now else "fresh"
    return "studied" if chapter_status != "not started" else "not yet"


def practise(p: Progress, concept: Concept, kind: Literal["seen", "produced"],
             correct: bool | None, now: datetime) -> Progress:
    """The progress after one result; see the module docstring for the rule."""
    if kind == "produced":
        p = replace(p, last_produced_at=now, produced_count=p.produced_count + 1,
                    error_count=p.error_count + (0 if correct else 1))
    else:
        p = replace(p, last_seen_at=now)

    if correct or (kind == "seen" and concept.mode == "receptive"):
        if p.first_correct_at is None:
            p = replace(p, first_correct_at=now, interval_days=concept.base_interval,
                        interval_grown_at=now)
        elif now - p.interval_grown_at >= timedelta(days=p.interval_days / 2):
            p = replace(p, interval_days=min(2 * p.interval_days, MAX_INTERVAL),
                        interval_grown_at=now)
        out = now + timedelta(days=p.interval_days)
        return replace(p, refresh_at=max(p.refresh_at or out, out))

    if p.first_correct_at is None:
        return p  # never got it right: nothing to refresh yet
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


class ConceptDetail(ConceptSummary):
    chapter: str
    difficulty: Literal["easy", "medium", "hard"]
    pitfall: str | None
    later: list[ConceptRef]  # refinements that come in later chapters
    see: list[ConceptRef]
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
    kind: Literal["seen", "produced"] = Field(
        ..., description="'produced': the user wrote or said Spanish that needed the concept. "
                         "'seen': you used it on purpose in a text the user read.")
    correct: bool | None = Field(
        None, description="For 'produced' only: false if the user got this concept wrong "
                          "anywhere in the session.")
    self_reported: bool = Field(
        False, description="True when the user told you they know it instead of using it.")
    sentence: str | None = Field(
        None, max_length=300, description="One of the user's sentences that used the concept.")

    @model_validator(mode="after")
    def _correct_for_produced(self):
        if (self.kind == "produced") != (self.correct is not None):
            raise ValueError("correct is required for 'produced', and only for it")
        return self


class ChapterUpdate(BaseModel):
    chapter: str = Field(..., min_length=1, max_length=80, description="A chapter id, e.g. 'es.ser'")
    status: Literal["started", "done"]


class ConceptChange(BaseModel):
    concept: str
    before: State
    after: State


class GrammarRecord(BaseModel):
    recorded: int                # results logged as events
    changed: list[ConceptChange]  # concepts whose state moved
    chapters: list[str]          # chapters whose status changed
    not_found: list[str]         # ids not in the curriculum, so not recorded


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

    def record(self, user_id: str, events: list[dict], concepts: list[dict],
               chapters: list[dict]) -> int:
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
    for ch in cur.chapters:
        if ch.level != level:
            level = ch.level
            lines += ["", level.upper()]
        status = _status(chapters, ch.id)
        states = [state(progress.get(c.id), status, now) for c in ch.concepts]
        practised = sum(s in ("fresh", "fading") for s in states)
        fading = states.count("fading")
        fading_total += fading
        line = f"{mark[status]} {ch.id}  {ch.title}"
        if status != "not started" or practised:
            line += f"  {practised}/{len(states)} practised"
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
        f"Fading concepts: {fading_total}.",
        "Key: ✓ done, → started, · not started. 'practised' counts concepts used correctly; "
        "fading ones are due to be worked back in. get_grammar_details lists a chapter's concepts.",
    ]
    return GrammarOverview(language=language, overview="\n".join(head + lines),
                           guide=teaching_guide())


def _summary(c: Concept, s: State) -> dict:
    return {"id": c.id, "title": c.title, "scope": c.scope, "state": s,
            "mode": c.mode, "variety": c.variety, "chunk": c.chunk}


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
                      concepts=[ConceptSummary(**_summary(c, concept_state(c))) for c in ch.concepts])
        for ch in (cur.chapter[i] for i in asked_chapters if i in cur.chapter)
    ]
    out_concepts = [
        ConceptDetail(**_summary(c, concept_state(c)), chapter=c.chapter_id,
                      difficulty=c.difficulty, pitfall=c.pitfall,
                      later=[ref(i) for i in c.later], see=[ref(i) for i in c.see],
                      refresh_at=(p.refresh_at.isoformat()
                                  if (p := progress.get(c.id)) and p.refresh_at else None))
        for c in (cur.concept[i] for i in asked_concepts if i in cur.concept)
    ]
    not_found = ([i for i in asked_chapters if i not in cur.chapter]
                 + [i for i in asked_concepts if i not in cur.concept])
    return GrammarDetails(chapters=out_chapters, concepts=out_concepts, not_found=not_found)


def record(store: GrammarStore, user_id: str, language: str, results: list[GrammarResult],
           chapter_updates: list[ChapterUpdate], now: datetime | None = None) -> GrammarRecord:
    now = now or _now()
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
        if u.chapter in cur.chapter:
            set_chapter(u.chapter, u.status)
        else:
            not_found.append(u.chapter)

    events, before, touched = [], {}, {}
    for r in results:
        c = cur.concept.get(r.concept)
        if c is None:
            not_found.append(r.concept)
            continue
        before.setdefault(c.id, state(progress.get(c.id), old_status[c.chapter_id], now))
        if r.kind == "produced":
            # Using a concept means its chapter is open, whatever the app said.
            set_chapter(c.chapter_id, "started")
        touched[c.id] = practise(touched.get(c.id) or progress.get(c.id) or Progress(),
                                 c, r.kind, r.correct, now)
        events.append({"concept_id": c.id, "kind": r.kind, "correct": r.correct,
                       "self_reported": r.self_reported, "sentence": r.sentence})

    new_status = old_status | {i: row["status"] for i, row in changed_chapters.items()}
    recorded = store.record(
        user_id, events,
        [{"concept_id": i} | p.to_row() for i, p in touched.items()],
        list(changed_chapters.values()),
    ) if events or changed_chapters else 0

    after = {i: state(touched[i], new_status[cur.concept[i].chapter_id], now) for i in touched}
    return GrammarRecord(
        recorded=recorded,
        changed=[ConceptChange(concept=i, before=before[i], after=after[i])
                 for i in after if before[i] != after[i]],
        chapters=[i for i in changed_chapters if new_status[i] != old_status[i]],
        not_found=list(dict.fromkeys(not_found)),
    )
