"""OAuth discovery and token restrictions for the MCP protected resource.

Supabase is the authorization server. Its access-token hook (supabase/migrations/*_mcp_oauth.sql)
adds this audience and a non-database role to OAuth grants. Signature and live
session verification stay in auth.verify_token, using Supabase's /user endpoint.
"""
import base64
import json
import math
import os
import time
from urllib.parse import urlsplit

from fastapi import APIRouter

from supabase_client import SUPABASE_URL

MCP_RESOURCE_URL = os.getenv(
    "MCP_RESOURCE_URL", "https://major-wynny-victorfriedrich-7c04e8cd.koyeb.app/mcp"
).rstrip("/")
_parts = urlsplit(MCP_RESOURCE_URL)
if (_parts.scheme not in ("https", "http") or not _parts.netloc
        or _parts.path != "/mcp" or _parts.query or _parts.fragment
        or _parts.username or _parts.password
        or (_parts.scheme == "http" and _parts.hostname not in ("localhost", "127.0.0.1"))):
    raise ValueError("MCP_RESOURCE_URL must be an HTTPS URL ending in /mcp (HTTP for localhost only)")
MCP_ISSUER = SUPABASE_URL.rstrip("/") + "/auth/v1"
MCP_METADATA_URL = f"{_parts.scheme}://{_parts.netloc}/.well-known/oauth-protected-resource/mcp"
MCP_PUBLIC_PATHS = {"/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"}
router = APIRouter()


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
@router.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
def protected_resource_metadata():
    return {
        "resource": MCP_RESOURCE_URL,
        "resource_name": "Langfour",
        "authorization_servers": [MCP_ISSUER],
        # No openid scope: an ID token isn't needed, and older Supabase projects
        # still use HS256, which cannot issue OIDC ID tokens.
        "scopes_supported": ["email"],
        "bearer_methods_supported": ["header"],
    }


def mcp_challenge(path: str, *, invalid: bool = False) -> dict[str, str]:
    if path.rstrip("/") != "/mcp":
        return {}
    challenge = f'Bearer resource_metadata="{MCP_METADATA_URL}", scope="email"'
    if invalid:
        challenge += ', error="invalid_token"'
    return {"WWW-Authenticate": challenge}


def token_claims(token: str) -> dict:
    """Decode for restrictions only; NEVER authenticates a bearer token."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        return claims if isinstance(claims, dict) else {}
    except (ValueError, UnicodeError):
        return {}


def is_oauth_token(claims: dict) -> bool:
    return "client_id" in claims or claims.get("role") == "langfour_mcp"


def valid_mcp_claims(claims: dict, user) -> bool:
    """Additional checks AFTER Supabase verified signature and live session.

    Supabase's /user endpoint requires authenticated as the first audience.
    The hook additionally binds OAuth tokens to our exact MCP resource URL.
    Its separate role prevents these tokens from using the Supabase Data API.
    """
    exp = claims.get("exp")
    return (
        claims.get("iss") == MCP_ISSUER
        and claims.get("aud") == ["authenticated", MCP_RESOURCE_URL]
        and claims.get("role") == "langfour_mcp"
        and isinstance(claims.get("client_id"), str) and bool(claims["client_id"])
        and claims.get("sub") == str(user.id)
        and claims.get("is_anonymous") is False
        and not getattr(user, "is_anonymous", False)
        and isinstance(exp, (int, float)) and not isinstance(exp, bool)
        and math.isfinite(exp) and exp > time.time()
    )
