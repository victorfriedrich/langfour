"""Regression checks for verification failures and structured-output fallback."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def nlp(monkeypatch):
    # Client construction needs configuration; all external calls are mocked.
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.signature")
    monkeypatch.setenv("REQUIRE_SERVICE_ROLE", "0")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    import nlp_processing
    return nlp_processing


def test_parse_propagates_verification_failure_without_adding_words(nlp, monkeypatch):
    monkeypatch.setattr(nlp, "identify_word_id", Mock(side_effect=ValueError("unknown")))
    monkeypatch.setattr(nlp, "verify_language", Mock(side_effect=TimeoutError("unavailable")))
    add_word = Mock()
    monkeypatch.setattr(nlp, "add_to_dictionary", add_word)

    with pytest.raises(TimeoutError, match="unavailable"):
        nlp.parse(["hola"], "video", "es")

    add_word.assert_not_called()


def test_high_level_tag_json_fallback_includes_category_contract(nlp, monkeypatch):
    calls = []

    def complete(**kwargs):
        format_type = kwargs["response_format"]["type"]
        calls.append(format_type)
        if format_type == "json_schema":
            raise ValueError("Provider does not support json_schema")

        prompt = "\n".join(message["content"] for message in kwargs["messages"])
        assert '"category"' in prompt
        for category in nlp.VALID_CATEGORIES:
            assert category in prompt
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({"category": "Products & Tech"}), refusal=None,
        ))])

    monkeypatch.setattr(nlp.client.chat.completions, "create", complete)

    assert nlp.get_high_level_tag("Laptop review", ["laptop"]) == "Products & Tech"
    assert calls == ["json_schema", "json_object"]
