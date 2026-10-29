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
"""

from typing import Annotated, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

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
        "read it, log it with record_exposure. When the user says they already know words "
        "they're learning, move them to known with set_word_status; that is a status change, "
        "never something to fake with record_practice."
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

    Only report active recall: the user translated a word you showed them ('recognize'),
    or came up with the word themselves ('produce'). Words that merely appeared in text
    you wrote are not practice. Use each word's dictionary form in the target language
    (e.g. 'hablar', not 'hablaba'). language is an ISO code: es, de, it or fr.

    Ask the user before calling this: the results can change when their flashcards come
    up for review. Wrong answers bring a card back sooner; right answers only count for
    cards that are due anyway.
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
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> Vocabulary:
    """The user's vocabulary in a language: how many words they know, are learning and
    have due for review, and a list of words with translations.

    status picks the list: 'due' are learning words whose review is due now, most overdue
    first, and the best words to practise; 'learning' are all words being learned, newest
    first; 'known' are words the user knows, newest first. language is an ISO code (es, de,
    it or fr); leave it out for the language the user is studying. Pass words to
    record_practice exactly as listed here (with the article, e.g. 'la casa').
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
    few learning words make good practice. Reading-only; nothing is recorded.
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
