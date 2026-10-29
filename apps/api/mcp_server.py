"""
Langfour as an MCP server, at /mcp, for LLM clients the user talks to.

Served by the API itself: auth.AuthMiddleware already requires a Supabase
session on every path that isn't public, and the tools call the Python code
directly. Stateless streamable HTTP with plain JSON responses, so nothing is
streamed through the BaseHTTPMiddleware auth layer and any instance can answer
any request.

Clients: anything that can send a bearer token (Claude Code, Cursor). ChatGPT
and claude.ai connectors expect OAuth 2.1 discovery, which isn't here yet.

Tools so far: record_practice (practice.py). The read tools from the design
discussion (get_vocabulary, score_text) come next.
"""

from typing import Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from practice import (
    PracticeAnswer,
    PracticeRequest,
    PracticeSummary,
    get_practice_store,
    record_practice,
)

mcp = FastMCP(
    "langfour",
    instructions=(
        "Langfour knows which words of a language the user is learning and schedules their "
        "flashcard reviews (often in RemNote). When you practise vocabulary with the user, "
        "report the results with record_practice at the end of the session."
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
def record_practice_tool(language: Literal["es", "de", "it", "fr"], answers: list[PracticeAnswer], ctx: Context) -> PracticeSummary:
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
