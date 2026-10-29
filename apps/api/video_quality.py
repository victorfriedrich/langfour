"""Rate a video transcript with Jev and decide whether it may be recommended.

One Decisions API request per video asks eight choice questions about the raw
transcript (sql/video_scores.sql stores the answers):

  filters   integrity (clean/patchy/garbled), foreign-language lesson, sung
  A         grammar level, A1..C1 mapped to 1..9           stored, not used yet
  C         content in the words, 1..10                    used in the floor
  D         developed thought, 1..10                       stored, not used yet
  E         transferable language, 1..10                   used in the floor

hidden() is the only rule the recommender applies: drop garbled transcripts,
lessons for another language and songs/poems, and videos whose average of C
and E is below QUALITY_FLOOR. Thresholds live here, not in the table, so they
can be re-tuned from the stored probabilities without new requests.

A and D are kept for later level matching and preferences. D runs about two
points higher than a blind Sonnet check on tutorials and lists, which is one
reason it is not in the floor. Why each prompt reads the way it does, and the
checks behind the thresholds: docs/plans/video-quality-filters.md.

Spanish only: the prompts' examples and grammar levels are Spanish. Other
languages are skipped, not scored, and therefore never hidden.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"      # pinned: the thresholds were measured against it
RUBRIC_VERSION = 1               # bump when a prompt changes; old rows are rescored
LANGUAGES = ("es",)

WHOLE_UP_TO = 3000               # words; longer transcripts are sampled
EXCERPT_WORDS = 1000
EXCERPT_AT = (0.2, 0.5, 0.8)

GARBLED_FROM = 0.6
FOREIGN_LESSON_FROM = 0.9
SUNG_FROM = 0.9
QUALITY_FLOOR = 5.0              # mean of C and E

PREAMBLE = ("The state holds an auto-generated Spanish YouTube transcript (no punctuation, no "
            "speaker labels): the whole transcript, or for long videos three excerpts taken at "
            "20%, 50% and 80%. Judge the video as a whole. ")

CHOICES: dict[str, tuple[str, dict[str, str]]] = {
    "integrity": (
        "Transcript integrity. Is this transcript readable Spanish, or did the automatic "
        "captioning fail? Missing punctuation and casual speech are normal and don't count as "
        "errors.",
        {"clean": "Reads as coherent Spanish speech; errors are rare and don't hide the meaning.",
         "patchy": "Mostly coherent, but some stretches are garbled or make no sense.",
         "garbled": "Large parts are word salad: real words in sequences no speaker would say."}),
    "foreign_lesson": (
        "Is this video teaching a language other than Spanish, for example English lessons for "
        "Spanish speakers?",
        {"yes": "Yes, it teaches another language.", "no": "No."}),
    "sung": (
        "Is most of this video sung or recited (a song, rap, or poem)?",
        {"yes": "Yes, most of it is sung or recited.", "no": "No."}),
    "grammar": (
        "Which CEFR level of Spanish grammar does a listener need to follow these sentences? "
        "Vocabulary doesn't count. Judge the grammar of typical stretches, not the single hardest "
        "sentence; a short and a long video with equally complex sentences must get the same "
        "level.",
        {"A1": "A1: present tense, ser/estar/tener/hay, very short simple sentences.",
         "A2": "A2: simple past and ir a, reflexives, short que/porque/cuando clauses, no subjunctive.",
         "B1": "B1: past tenses combined, object pronouns, common subordinate clauses, subjunctive "
               "in set phrases.",
         "B2": "B2: subjunctive and conditionals used freely, si-clauses, longer complex sentences.",
         "C1": "C1 and above: rare tenses, compound subjunctive, dense or formal structure."}),
}
GRAMMAR_SCORES = {"A1": 1, "A2": 3, "B1": 5, "B2": 7, "C1": 9}

SCALES: dict[str, tuple[str, dict[int, str]]] = {
    "content": (
        "Content in the words. How much of the video's meaning is carried by the spoken words "
        "themselves? Look for speech that points at the screen (\"mira esto\", \"ahí\", \"eso de "
        "ahí\"), reactions to things that are only shown, sponsor reads, subscribe-and-like "
        "requests, long greetings and goodbyes, padding and repeating the same point. Compare "
        "that with speech that narrates, explains, describes or tells a story a listener could "
        "follow with their eyes closed.",
        {1: "Mostly reactions to what's on screen and filler; without the video, almost nothing is said.",
         5: "A real thread of content, but often interrupted by references to the screen or by padding.",
         10: "Nearly every line adds information, story or opinion that the words alone convey."}),
    "developed": (
        "Developed thought. Do speakers develop ideas over several sentences, or do they only "
        "react and move on? Look for reasons, examples, comparisons, consequences, stories with "
        "a beginning and an end, and opinions that are argued rather than just stated. "
        "One-liners, isolated exclamations and quick exchanges that never go anywhere score low.",
        {1: "Short reactions and fragments, no idea lasts longer than one sentence.",
         5: "Some topics get a few sentences of explanation or story, but they're often cut short.",
         10: "Sustained explanation, argument or narrative that develops through the video."}),
    "transferable": (
        "Transferable language. Would a learner meet or use this language outside this video? "
        "Look for general vocabulary and common expressions from everyday life, work, "
        "relationships, opinions and feelings. Score down for game or hobby jargon, in-group "
        "memes and catchphrases, long runs of brand names and names of people and places, slang "
        "only one community uses, and technical terms that the topic needs but that are rare "
        "elsewhere.",
        {1: "Dominated by niche jargon, names and in-group language.",
         5: "General language mixed with substantial niche vocabulary.",
         10: "Almost entirely language that is useful in many everyday situations."}),
}


def _scale_criteria(anchors: dict[int, str]) -> dict[str, str]:
    out = {}
    for k in range(1, 11):
        if k in anchors:
            out[str(k)] = anchors[k]
        else:
            lo = max(a for a in anchors if a < k)
            hi = min(a for a in anchors if a > k)
            out[str(k)] = f"Between {lo} ({anchors[lo]}) and {hi} ({anchors[hi]})."
    return out


QUESTIONS = {
    **{key: {"type": "choice", "instructions": PREAMBLE + text, "criteria": criteria}
       for key, (text, criteria) in CHOICES.items()},
    **{key: {"type": "choice", "instructions": PREAMBLE + text, "criteria": _scale_criteria(anchors)}
       for key, (text, anchors) in SCALES.items()},
}


def excerpts(words: list[str]) -> list[str]:
    """The whole transcript, or three windows of a long one."""
    if len(words) <= WHOLE_UP_TO:
        return [" ".join(words)]
    out = []
    for at in EXCERPT_AT:
        start = max(0, min(len(words) - EXCERPT_WORDS, int(len(words) * at) - EXCERPT_WORDS // 2))
        out.append(" ".join(words[start:start + EXCERPT_WORDS]))
    return out


def transcript_words(processed: dict) -> list[str]:
    """Words of a processed transcript file, in order."""
    return "".join(t.get("content", "") for t in processed.get("content", [])).split()


def client() -> httpx.Client:
    return httpx.Client(timeout=60, headers={
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})


def ask(http: httpx.Client, title: str, words: list[str], attempts: int = 5) -> dict[str, Any]:
    """Jev's answers to every question. Retries transient errors, and the
    occasional response that leaves a question out."""
    state = {"title": title, "excerpts": excerpts(words)}
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            r = http.post(URL, json={"model": MODEL, "state": state, "questions": QUESTIONS})
            if r.status_code == 200:
                answers = r.json().get("answers", {})
                if all(k in answers for k in QUESTIONS):
                    return answers
                last = RuntimeError(f"Jev left out {sorted(set(QUESTIONS) - set(answers))}")
            else:
                last = RuntimeError(f"Jev HTTP {r.status_code}: {r.text[:200]}")
                if r.status_code < 500 and r.status_code not in (408, 429):
                    break
        except httpx.HTTPError as e:
            last = e
        time.sleep(2 ** attempt)
    raise last or RuntimeError("Jev did not answer")


def row(video_id: str, language: str, answers: dict[str, Any]) -> dict[str, Any]:
    """The video_scores row for Jev's answers."""
    p = {k: answers[k]["probabilities"] for k in QUESTIONS}

    def expected(key: str) -> float:
        return round(sum(int(k) * v for k, v in p[key].items()), 2)

    return {
        "video_id": video_id,
        "language": language,
        "rubric_version": RUBRIC_VERSION,
        "integrity": max(p["integrity"], key=p["integrity"].get),
        "p_garbled": p["integrity"].get("garbled", 0.0),
        "p_foreign_lesson": p["foreign_lesson"].get("yes", 0.0),
        "p_sung": p["sung"].get("yes", 0.0),
        "grammar": round(sum(GRAMMAR_SCORES[k] * v for k, v in p["grammar"].items()), 2),
        "content": expected("content"),
        "developed": expected("developed"),
        "transferable": expected("transferable"),
        "jev": p,
    }


def hidden(scores: dict[str, Any]) -> str | None:
    """Why a scored video is not recommended, or None to keep it."""
    if scores["p_garbled"] >= GARBLED_FROM:
        return "garbled"
    if scores["p_foreign_lesson"] >= FOREIGN_LESSON_FROM:
        return "foreign_lesson"
    if scores["p_sung"] >= SUNG_FROM:
        return "sung"
    if (scores["content"] + scores["transferable"]) / 2 < QUALITY_FLOOR:
        return "low_quality"
    return None


def score_and_store(sb, http: httpx.Client, video_id: str, language: str,
                    title: str, words: list[str]) -> dict[str, Any] | None:
    """Score one transcript and upsert its row. None for unscored languages."""
    if language not in LANGUAGES or not words:
        return None
    scores = row(video_id, language, ask(http, title, words))
    sb.table("video_scores").upsert(scores, on_conflict="video_id").execute()
    return scores


def hidden_ids(sb, language: str | None = None) -> set[str]:
    """Video ids the recommender must skip, under the current thresholds."""
    cols = "video_id,p_garbled,p_foreign_lesson,p_sung,content,transferable"
    out, page = set(), 0
    while True:
        q = sb.table("video_scores").select(cols).order("video_id")
        if language:
            q = q.eq("language", language)
        rows = q.range(page * 1000, page * 1000 + 999).execute().data
        out |= {r["video_id"] for r in rows if hidden(r)}
        if len(rows) < 1000:
            return out
        page += 1
