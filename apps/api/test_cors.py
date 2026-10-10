"""CORS for the browser extensions' origins.

The Safari extension's origin carries a per-install UUID, so app.py allows it
by pattern; anything else outside the allowlist must still be refused.
"""
import os

# app.py builds the Supabase client at import time; these tests never make a
# network request. Same stubs as test_flashcards.py.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("REQUIRE_SERVICE_ROLE", "0")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("DEEPINFRA_API_KEY", "test-key")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.test-signature",
)

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

client = TestClient(app)


def preflight(origin: str):
    return client.options(
        "/api/translate-word",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def test_safari_extension_origin_is_allowed():
    origin = "safari-web-extension://6F1D2C3B-9A4E-4F7B-8C21-0D5E6A7B8C9D"
    response = preflight(origin)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_unknown_origin_is_refused():
    response = preflight("https://evil.example")
    assert "access-control-allow-origin" not in response.headers


def test_lookalike_safari_origin_is_refused():
    response = preflight("safari-web-extension://abc.evil.example")
    assert "access-control-allow-origin" not in response.headers
