"""
Langfour as an MCP server, at /mcp, for LLM clients the user talks to.

Served by the API itself: auth.AuthMiddleware already requires a Supabase
session on every path that isn't public, and the tools call the Python code
directly. Stateless streamable HTTP with plain JSON responses, so nothing is
streamed through the BaseHTTPMiddleware auth layer and any instance can answer
any request.

Clients discover Supabase OAuth through mcp_auth.py. See docs/mcp-oauth.md
for project setup and connecting ChatGPT or Claude.

Tools: get_vocabulary and score_text read (vocabulary.py); record_practice
(practice.py), record_exposure and set_word_status (vocabulary.py) write.
get_grammar_overview and get_grammar_details read the grammar curriculum and
the user's place in it; record_grammar writes (grammar.py).
"""

from typing import Annotated, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

import grammar
from grammar import (
    MAX_DETAIL_CHAPTERS,
    MAX_DETAIL_CONCEPTS,
    ChapterUpdate,
    GrammarDetails,
    GrammarOverview,
    GrammarRecord,
    GrammarResult,
    get_grammar_store,
)
from practice import (
    PracticeAnswer,
    PracticeRequest,
    PracticeSummary,
    get_practice_store,
    record_practice,
)
from vocabulary import (
    MAX_TEXT,
    ExposureSummary,
    Language,
    StatusChange,
    TextScore,
    Vocabulary,
    get_vocabulary,
    get_vocabulary_store,
    record_exposure,
    score_text,
    set_word_status,
)

mcp = FastMCP(
    "langfour",
    instructions=(
        "Langfour knows which words of a language the user is learning and schedules their "
        "flashcard reviews, itself or in a connected app such as RemNote. Before practising "
        "vocabulary with the user, pick words with get_vocabulary (due words first); at the end "
        "of the session, report the results with record_practice. When you write a text for "
        "the user to read in the language, check its level with score_text, and once they have "
        "read it, log it with record_exposure. Take the user at their word about what they "
        "know: words they know outright go to known with set_word_status, and words they say "
        "they can read but not produce get a correct 'recognize' answer, self_reported, with "
        "record_practice. Don't quiz them first unless they ask. "
        "Langfour also knows where the user is in their grammar book. Before you write a text "
        "for them or teach grammar, read get_grammar_overview once and follow the guide it "
        "returns; fetch get_grammar_details only for the chapters the conversation is about. "
        "Teach in the guide's small lessons, one step per message, and don't move on until "
        "a concept is learned. At the end of each lesson, report every sentence the user "
        "wrote and every exercise answer with record_grammar."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/mcp",
)


def _user_id(ctx: Context) -> str:
    """The user auth.AuthMiddleware verified for this HTTP request."""
    request = ctx.request_context.request
    user = getattr(getattr(request, "state", None), "user", None)
    if user is None:  # unreachable behind the middleware; refuse rather than guess
        raise PermissionError("Not signed in")
    return str(user.id)


@mcp.tool(name="record_practice", annotations=ToolAnnotations(
    title="Record vocabulary practice",
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False,
))
def record_practice_tool(language: Language, answers: list[PracticeAnswer], ctx: Context) -> PracticeSummary:
    """Record the results of a vocabulary practice session with the user, once, at its end.

    An answer is the user translating a word you showed them ('recognize') or coming up
    with it themselves ('produce'), or the user telling you how they'd do: "I can read
    these" is a correct 'recognize' answer for each word, with self_reported set. Words
    that merely appeared in text you wrote are not practice. Use each word's dictionary
    form in the target language (e.g. 'hablar', not 'hablaba'). language is an ISO code:
    es, de, it or fr.

    Results move flashcard reviews: wrong answers bring a card back sooner; right answers
    only count for cards that are due anyway. A wrong answer also lists the word under
    mistakes in get_vocabulary until the user gets it right, known words included; give it
    a note saying what they wrote instead.

    When the user writes a wrong or made-up word (apartamiento for 'flat'), record a wrong
    'produce' answer for the word from their own vocabulary they should have used (piso,
    if they know it), not just the dictionary word for it. Say which words you're
    recording before you call this.
    """
    req = PracticeRequest(language=language, answers=answers)
    return record_practice(get_practice_store(), _user_id(ctx), req)


@mcp.tool(name="get_vocabulary", annotations=ToolAnnotations(
    title="See vocabulary", readOnlyHint=True, openWorldHint=False,
))
def get_vocabulary_tool(
    ctx: Context,
    status: Literal["due", "learning", "known"] = "due",
    language: Language | None = None,
    limit: Annotated[int, Field(ge=1)] = 50,
) -> Vocabulary:
    """The user's vocabulary in a language: how many words they know, are learning and
    have due for review, and a list of words with translations.

    status picks the list: 'due' are learning words whose review is due now, most overdue
    first, and the best words to practise; 'learning' are all words being learned, newest
    first; 'known' are words the user knows, newest first. language is an ISO code (es, de,
    it or fr); leave it out for the language the user is studying. Pass words to
    record_practice exactly as listed here (with the article, e.g. 'la casa'). limit has
    no maximum; counts says how many words there are, at about 90 bytes per word listed.

    mistakes lists words the user last got wrong in practice, newest first, with a note:
    work one to three of them into the session and record the result.
    """
    return get_vocabulary(get_vocabulary_store(), _user_id(ctx), language, status, limit)


@mcp.tool(name="score_text", annotations=ToolAnnotations(
    title="Check a text's level", readOnlyHint=True, openWorldHint=False,
))
def score_text_tool(
    language: Language,
    text: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)],
    ctx: Context,
) -> TextScore:
    """How much of a text in the target language the user would understand: the share of
    its words they know, are learning or haven't met, and which learning and new words it
    contains. Names and other words that aren't vocabulary are left out.

    Use it to pitch a text at the user's level: around 95% known reads comfortably, and a
    few learning words make good practice. Reading-only and cheap, so scoring a draft
    several times while writing it is fine; nothing is recorded.
    """
    return score_text(get_vocabulary_store(), _user_id(ctx), language, text)


@mcp.tool(name="record_exposure", annotations=ToolAnnotations(
    title="Log a text the user read",
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False,
))
def record_exposure_tool(
    language: Language,
    text: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)],
    ctx: Context,
) -> ExposureSummary:
    """Log that the user read a text in the target language, once per text, after they
    have read it. Langfour notes each word they're learning or haven't met as seen; it
    doesn't change their flashcard schedule.

    Only for texts the user chose to read (a story or article they asked for), not for
    everything you wrote in the conversation.
    """
    return record_exposure(get_vocabulary_store(), _user_id(ctx), language, text)


@mcp.tool(name="set_word_status", annotations=ToolAnnotations(
    title="Mark words known or learning",
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False,
))
def set_word_status_tool(
    language: Language,
    words: Annotated[list[Annotated[str, Field(min_length=1, max_length=64)]],
                     Field(min_length=1, max_length=200)],
    status: Literal["known", "learning"],
    ctx: Context,
) -> StatusChange:
    """Move words of the user's list to known (they stop coming up for review) or back
    to learning (they get a flashcard again). Use it when the user says they already know
    words they're learning, or wants a known word back.

    Pass words as get_vocabulary lists them (with the article, e.g. 'la casa'), or as the
    user saw them ('encontré' finds encontrar).
    When you pick the words yourself, show the user the list and change only the ones
    they confirm. not_found lists words that aren't in their list in that language.
    """
    return set_word_status(get_vocabulary_store(), _user_id(ctx), language, words, status)


@mcp.tool(name="get_grammar_overview", annotations=ToolAnnotations(
    title="See grammar progress", readOnlyHint=True, openWorldHint=False,
))
def get_grammar_overview_tool(ctx: Context, language: Language | None = None) -> GrammarOverview:
    """Where the user is in their grammar book: every chapter in teaching order, which
    ones they started or finished, how many concepts they've learned and how many are
    fading (due to be worked back in), the mistakes they made that are still to revise,
    with a note on each, plus a guide for teaching from it.

    Call it once at the start of a session in which you'll write in the language for the
    user or teach them grammar, and follow the guide. language is an ISO code; leave it
    out for the language the user is studying.
    """
    return grammar.get_overview(get_grammar_store(), _user_id(ctx), language)


@mcp.tool(name="get_grammar_details", annotations=ToolAnnotations(
    title="See grammar chapters and concepts", readOnlyHint=True, openWorldHint=False,
))
def get_grammar_details_tool(
    ctx: Context,
    chapters: Annotated[list[str], Field(max_length=MAX_DETAIL_CHAPTERS)] = [],  # noqa: B006
    concepts: Annotated[list[str], Field(max_length=MAX_DETAIL_CONCEPTS)] = [],  # noqa: B006
    language: Language | None = None,
) -> GrammarDetails:
    """The concepts of a few chapters with the user's state of each (chapter ids from
    get_grammar_overview), or a few concepts in full: pitfall, the refinements that come
    later, related concepts, and the forms the user still has to produce.

    A concept's scope says exactly what it covers; teach that and nothing from a later
    concept. Fetch only the chapters the conversation is about: a text practising por and
    para needs that chapter, not the subjunctive. not_found lists unknown ids.
    """
    return grammar.get_details(get_grammar_store(), _user_id(ctx), language, chapters, concepts)


@mcp.tool(name="record_grammar", annotations=ToolAnnotations(
    title="Record grammar practice",
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False,
))
def record_grammar_tool(
    language: Language,
    results: Annotated[list[GrammarResult], Field(max_length=100)],
    ctx: Context,
    chapters: Annotated[list[ChapterUpdate], Field(max_length=20)] = [],  # noqa: B006
) -> GrammarRecord:
    """Record grammar practice at the end of each lesson: one result per sentence or answer.

    'produced': one sentence the user wrote or said in full that needed the concept, with
    the sentence exactly as they wrote it; correct is whether this concept was right in
    it. Errors in other concepts don't count against it. 'recognized': one answer to a
    choice or fill-in exercise; it's logged but doesn't count toward learning. 'seen': a
    concept you used on purpose in a text the user read (the one you taught, or a fading
    one you worked in), not every rule a text happens to contain.

    Record every grammar mistake the user makes, in any concept, including chapters they
    haven't started (look the concept up with get_grammar_details), as a wrong result
    with a short note. It stays flagged for revision until they next use it correctly.

    A concept is learned only after enough correct sentences covering enough of its
    forms; to_learn says what each practised concept still needs. Never tell the user a
    concept is learned or done unless changed shows it fresh. self_reported is only for
    a user who tells you, without an exercise, that they already know the concept.

    chapters marks a chapter 'started' when you begin teaching it. 'done' is accepted
    once every concept in it is learned (not_done lists the ones refused), or with
    self_reported when the user says they already know the chapter.
    """
    return grammar.record(get_grammar_store(), _user_id(ctx), language, results, chapters)
