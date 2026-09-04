"""
Authentication for the Langfour backend.

Design note: this is deliberately a *deny-by-default* middleware rather than a
per-endpoint dependency. The previous approach attached `Depends(get_current_user)`
to individual routes, and 15 of 22 endpoints silently went out without it --
including /api/translate and /api/translate-word, which spend OpenAI credits on
behalf of anyone who finds the URL. The URL is discoverable: it ships in the
Chrome extension bundle as REACT_APP_BACKEND_URL.

With a middleware, a newly added endpoint is protected unless someone
deliberately adds it to PUBLIC_PATHS.
"""

import os
import time
import logging
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from supabase import create_client, Client

logger = logging.getLogger(__name__)

security = HTTPBearer()

from supabase_client import supabase as _supabase

# ---------------------------------------------------------------------------
# Paths reachable without a bearer token. Keep this list short and justified.
# ---------------------------------------------------------------------------
PUBLIC_PATHS = {
    "/",              # health check, used by Koyeb's probe
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
}

# ---------------------------------------------------------------------------
# Token cache.
#
# supabase.auth.get_user(token) is a network round trip to GoTrue. Doing that
# on every request adds latency to each call and makes the backend's
# availability depend on the auth service. Cache successful verifications for
# a short TTL, keyed by the token itself.
#
# The TTL is deliberately shorter than the 3600s jwt_expiry in config.toml, so
# a revoked session stops working within the TTL window rather than the full
# token lifetime.
# ---------------------------------------------------------------------------
_TOKEN_TTL_SECONDS = 120
_token_cache: dict[str, tuple[float, object]] = {}
_CACHE_MAX = 10_000


def _cache_get(token: str):
    entry = _token_cache.get(token)
    if not entry:
        return None
    expires_at, user = entry
    if time.monotonic() > expires_at:
        _token_cache.pop(token, None)
        return None
    return user


def _cache_put(token: str, user) -> None:
    # Crude bound. If the cache is full, drop it wholesale rather than grow
    # without limit; re-verification is correct, just slower.
    if len(_token_cache) >= _CACHE_MAX:
        _token_cache.clear()
    _token_cache[token] = (time.monotonic() + _TOKEN_TTL_SECONDS, user)


def verify_token(token: str):
    """Return the Supabase user for a bearer token, or None if invalid."""
    cached = _cache_get(token)
    if cached is not None:
        return cached

    try:
        result = _supabase.auth.get_user(token)
    except Exception as exc:
        logger.warning("Token verification failed: %s", exc)
        return None

    user = getattr(result, "user", None)
    if user is None:
        return None

    _cache_put(token, user)
    return user


def _extract_bearer(request: Request) -> Optional[str]:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


class AuthMiddleware(BaseHTTPMiddleware):
    """Rejects any request without a valid Supabase bearer token."""

    async def dispatch(self, request: Request, call_next):
        # CORS preflight carries no credentials by design.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in PUBLIC_PATHS:
            return await call_next(request)

        token = _extract_bearer(request)
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing bearer token"},
            )

        user = verify_token(token)
        if user is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authentication credentials"},
            )

        # Downstream handlers read this instead of re-verifying.
        request.state.user = user
        return await call_next(request)


async def get_current_user(request: Request):
    """
    FastAPI dependency. Kept for the endpoints that already declare
    `Depends(get_current_user)` -- it now reads the user the middleware
    already verified, so there is no second network call.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    return user
