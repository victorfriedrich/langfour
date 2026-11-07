import os

# supabase_client builds its client at import time; nothing here touches the network.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("REQUIRE_SERVICE_ROLE", "0")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.test-signature",
)

from supabase_client import supabase


def _http2(client) -> bool:
    return client._transport._pool._http2


def test_shared_client_speaks_http1():
    """Request threads share this client. Over HTTP/2 they share one connection,
    and concurrent queries break it (ConnectionTerminated on Koyeb)."""
    assert not _http2(supabase.postgrest.session)
    assert not _http2(supabase.schema("public").session)
    assert not _http2(supabase.auth._http_client)
