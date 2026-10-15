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


def test_parse_propagates_jev_failure_without_adding_words(nlp, monkeypatch):
    monkeypatch.setattr(nlp, "identify_word_id", Mock(side_effect=ValueError("unknown")))
    monkeypatch.setattr(nlp, "CandidateIndex", Mock(return_value=Mock(candidates=Mock(return_value=[]))))
    monkeypatch.setattr(nlp, "match", Mock(side_effect=TimeoutError("unavailable")))
    add_form = Mock()
    monkeypatch.setattr(nlp, "add_wordform", add_form)

    with pytest.raises(TimeoutError, match="unavailable"):
        nlp.parse(["hola"], "video", "es")

    add_form.assert_not_called()


def test_parse_attaches_confident_matches_and_records_the_rest(nlp, monkeypatch):
    from word_matching import Match
    monkeypatch.setattr(nlp, "identify_word_id", Mock(side_effect=ValueError("unknown")))
    monkeypatch.setattr(nlp, "CandidateIndex", Mock(return_value=Mock(candidates=Mock(return_value=[]))))
    outcomes = {
        "editaron": Match("editaron", ["editar"], 7, "attach", 0.9, 0.9, {}),
        "smosh": Match("smosh", ["smash"], None, "not_a_word", 0.2, 0.05, {}),
        "teletrabajo": Match("teletrabajo", ["teletrabajar"], None, "pending", 0.5, 0.9, {}),
    }
    monkeypatch.setattr(nlp, "match", lambda client, index, word, language: outcomes[word])
    monkeypatch.setattr(nlp, "invalid_root_ids", Mock(return_value=set()))
    monkeypatch.setattr(nlp, "existing_wordforms", Mock(return_value={}))
    add_form = Mock(return_value=7)
    monkeypatch.setattr(nlp, "add_wordform", add_form)
    record = Mock()
    monkeypatch.setattr(nlp, "record_pending_words", record)

    result = nlp.parse(["editaron", " ", "smosh", " ", "teletrabajo", " ", "editaron"], "vid", "es")

    add_form.assert_called_once_with("editaron", 7, "es", status="valid")
    assert [r.get("id") for r in result] == [7, None, None, None, None, None, 7]
    rows = record.call_args.args[0]
    assert {(r["word"], r["outcome"]) for r in rows} == {("smosh", "not_a_word"),
                                                         ("teletrabajo", "pending")}


@pytest.mark.parametrize("existing, expected_id", [("valid", 7), ("invalid", None)])
def test_parse_keeps_the_verdict_of_a_form_row_the_cache_left_out(nlp, monkeypatch,
                                                                  existing, expected_id):
    from word_matching import Match
    monkeypatch.setattr(nlp, "identify_word_id", Mock(side_effect=ValueError("unknown")))
    monkeypatch.setattr(nlp, "CandidateIndex", Mock(return_value=Mock(candidates=Mock(return_value=[]))))
    monkeypatch.setattr(nlp, "invalid_root_ids", Mock(return_value=set()))
    monkeypatch.setattr(nlp, "match", Mock(return_value=Match("goliat", ["el goliat"], 7,
                                                              "attach", 0.9, 0.9, {})))
    monkeypatch.setattr(nlp, "existing_wordforms", Mock(return_value={(7, "goliat"): existing}))
    add_form = Mock()
    monkeypatch.setattr(nlp, "add_wordform", add_form)
    monkeypatch.setattr(nlp, "record_pending_words", Mock())

    assert nlp.parse(["goliat"], "vid", "es")[0].get("id") == expected_id
    add_form.assert_not_called()


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


@pytest.mark.parametrize('rejected, expected', [(False, 'valid'), (True, 'flagged')])
def test_dictionary_review_returns_status(nlp, monkeypatch, rejected, expected):
    monkeypatch.setattr(nlp, 'verify_and_translate', Mock(return_value=SimpleNamespace(
        definitely_not_valid=rejected, translation='take out',
    )))
    assert nlp._review('sacar', 'verb', ['sacaran'], 'es') == (expected, 'take out')


def test_failed_dictionary_review_stays_flagged_for_audit(nlp, monkeypatch):
    monkeypatch.setattr(nlp, 'verify_and_translate', Mock(side_effect=TimeoutError('unavailable')))
    assert nlp._review('sacar', 'verb', ['sacaran'], 'es') == ('flagged', None)


def test_dictionary_creation_preserves_a_rejected_root(nlp, monkeypatch):
    monkeypatch.setattr(nlp, 'get_word_root', Mock(return_value={'key': 'edit', 'type': 'verb'}))
    existing = Mock(return_value={'id': 20, 'status': 'invalid'})
    monkeypatch.setattr(nlp, 'find_dictionary_root', existing)
    actions = {}
    for name in ('add_wordform', 'generate_alternatives', '_review', 'save_to_supabase'):
        actions[name] = Mock()
        monkeypatch.setattr(nlp, name, actions[name])

    assert nlp.add_to_dictionary('edit', 'video', 'es') is None
    existing.assert_called_once_with('edit', 'es')
    for action in actions.values():
        action.assert_not_called()


def test_new_form_can_still_attach_to_an_existing_valid_root(nlp, monkeypatch):
    monkeypatch.setattr(nlp, 'get_word_root', Mock(return_value={'key': 'sacar', 'type': 'verb'}))
    monkeypatch.setattr(nlp, 'find_dictionary_root', Mock(return_value={'id': 10, 'status': 'valid'}))
    monkeypatch.setattr(nlp, '_review', Mock(return_value=('valid', 'take out')))
    add = Mock(return_value=10)
    monkeypatch.setattr(nlp, 'add_wordform', add)

    assert nlp.add_to_dictionary('sacaran', 'video', 'es') == 10
    add.assert_called_once_with('sacaran', 10, 'es', status='valid')
