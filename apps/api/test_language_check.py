"""/api/language-check: off unless the account has it, one Jev request per paragraph."""
import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("REQUIRE_SERVICE_ROLE", "0")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("DEEPINFRA_API_KEY", "test-key")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.test-signature",
)

import pytest
from fastapi.testclient import TestClient

import auth
import language_check
from app import app

AUTH = {"authorization": "Bearer ordinary-session"}
TEXT = "my friends gave me unexpected news"
ME = [TEXT.index(" me ") + 1, TEXT.index(" me ") + 3]


@pytest.fixture
def account(monkeypatch):
    monkeypatch.setattr(auth, "verify_token", lambda t: SimpleNamespace(id="user-1", is_anonymous=False))
    flag = {"on": True}
    monkeypatch.setattr(language_check, "enabled_for", lambda user_id: flag["on"])
    return flag


client = TestClient(app)


def test_reports_the_account_setting(account):
    assert client.get("/api/language-check", headers=AUTH).json() == {"enabled": True}
    account["on"] = False
    assert client.get("/api/language-check", headers=AUTH).json() == {"enabled": False}


def test_refuses_when_the_account_has_it_off(account, monkeypatch):
    account["on"] = False
    asked = []
    monkeypatch.setattr(language_check, "ask_jev", lambda *a: asked.append(a))
    response = client.post("/api/language-check", headers=AUTH, json={
        "language": "es", "blocks": [{"text": TEXT, "words": [ME]}]})
    assert response.status_code == 403
    assert asked == []


def test_refuses_offsets_outside_the_text(account):
    response = client.post("/api/language-check", headers=AUTH, json={
        "language": "es", "blocks": [{"text": "hola", "words": [[2, 9]]}]})
    assert response.status_code == 400


def test_thresholds_each_block_and_passes_failures_on(account, monkeypatch):
    async def fake_ask(client, code, block):
        assert code == "es"
        return None if block.text == "broken" else [0.05, 0.9][:len(block.words)]

    monkeypatch.setattr(language_check, "ask_jev", fake_ask)
    response = client.post("/api/language-check", headers=AUTH, json={
        "language": "spanish",
        "blocks": [{"text": TEXT, "words": [ME, [0, 2]]}, {"text": "broken", "words": [[0, 6]]},
                   {"text": "nada", "words": []}]})
    assert response.status_code == 200
    assert response.json()["blocks"] == [
        {"in_language": [False, True], "p": [0.05, 0.9]}, None, {"in_language": [], "p": []}]


def test_asks_jev_about_each_word_with_its_neighbourhood():
    sent = []

    class FakeClient:
        async def post(self, url, json):
            sent.append(json)
            return SimpleNamespace(status_code=200, json=lambda: {"answers": {
                "q0": {"probabilities": {"es": 0.1, "en": 0.85, "other": 0.05}}}})

    block = language_check.Block(text=TEXT, before="Last Saturday", after="", words=[ME])
    assert asyncio.run(language_check.ask_jev(FakeClient(), "es", block)) == [0.1]
    request = sent[0]
    assert request["model"] == language_check.MODEL
    assert request["state"] == {"before": "Last Saturday", "line": TEXT, "after": ""}
    q = request["questions"]["q0"]
    assert q["type"] == "choice" and set(q["criteria"]) == {"es", "en", "other"}
    assert "gave [me] unexpected" in q["instructions"]
    assert q["criteria"]["es"].startswith("Spanish:")
