"""
Single source of truth for the Supabase client.

Why this module exists
----------------------
Nine separate files used to call `create_client(SUPABASE_URL, SUPABASE_KEY)`
independently. Nobody could tell from the code which key was actually
configured, and the deployed value turned out to be the **anon** key rather
than service_role.

That is invisible while RLS is off -- the anon key can read and write
everything, so the backend worked. The moment RLS is enabled it becomes
catastrophic and silent: PostgREST returns `[]` with HTTP 200 for every SELECT,
so `initialize_cache()` loads an empty word cache and the whole NLP pipeline
starts treating every word as unknown, without a single error in the logs.

This module makes that failure impossible to reproduce quietly: it inspects the
key's own `role` claim at import time and refuses to start (or screams, if you
opt out) when the backend is not running as service_role.
"""

import base64
import json
import logging
import os
import sys

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")

# SUPABASE_SERVICE_ROLE_KEY is the canonical name. SUPABASE_KEY is accepted as a
# fallback so an old deployment still boots, but it is reported loudly.
_KEY_VAR = "SUPABASE_SERVICE_ROLE_KEY"
SUPABASE_KEY = os.getenv(_KEY_VAR)

if not SUPABASE_KEY:
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    if SUPABASE_KEY:
        _KEY_VAR = "SUPABASE_KEY"
        logger.warning(
            "Using deprecated SUPABASE_KEY. Rename this variable to "
            "SUPABASE_SERVICE_ROLE_KEY so the intended role is unambiguous."
        )

# Set REQUIRE_SERVICE_ROLE=0 only to keep an old deployment limping while RLS is
# still off. With RLS on, a non-service_role key is a guaranteed silent outage.
REQUIRE_SERVICE_ROLE = os.getenv("REQUIRE_SERVICE_ROLE", "1") not in ("0", "false", "False")


def _jwt_role(token: str) -> str | None:
    """Read the `role` claim from a Supabase API key. Local only -- no network,
    no signature check: we are identifying our own configuration, not trusting
    a caller."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("role")
    except Exception:
        return None


def _verify_key() -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must both be set."
        )

    role = _jwt_role(SUPABASE_KEY)

    if role == "service_role":
        logger.info("Supabase client authenticated as service_role.")
        return

    message = (
        f"\n{'=' * 78}\n"
        f"  SUPABASE KEY MISCONFIGURED\n"
        f"{'=' * 78}\n"
        f"  {_KEY_VAR} carries role: {role!r}\n"
        f"  Expected: 'service_role'\n\n"
        f"  The backend reads and writes rows belonging to ALL users. It can\n"
        f"  only do that with the service_role key, which bypasses RLS.\n\n"
        f"  With the anon key and RLS enabled, every SELECT silently returns\n"
        f"  zero rows with HTTP 200 -- no exception is raised anywhere. The\n"
        f"  word cache loads empty and the NLP pipeline produces wrong output\n"
        f"  with no visible error.\n\n"
        f"  Fix: Supabase Dashboard -> Project Settings -> API Keys ->\n"
        f"       'service_role' (click Reveal). Set it as\n"
        f"       SUPABASE_SERVICE_ROLE_KEY.\n"
        f"{'=' * 78}"
    )

    if REQUIRE_SERVICE_ROLE:
        logger.critical(message)
        raise RuntimeError(
            f"Refusing to start: {_KEY_VAR} has role {role!r}, expected 'service_role'. "
            "Set REQUIRE_SERVICE_ROLE=0 to override (unsafe once RLS is on)."
        )

    logger.critical(message)
    print(message, file=sys.stderr)


_verify_key()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

__all__ = ["supabase", "SUPABASE_URL", "SUPABASE_KEY"]
