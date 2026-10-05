"""The word cache: which root a token links to when roots share a form."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def db(monkeypatch):
    # Client construction needs configuration; no request is made.
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.signature")
    monkeypatch.setenv("REQUIRE_SERVICE_ROLE", "0")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    import database
    return database


def test_a_shared_form_stays_with_the_older_root(db, monkeypatch):
    """'editaron' is a form of the real root 'editar' and, since a later video,
    of the English root 'edit' too. Roots load in id order, and the junk copy is
    always the newer one, so the first root must keep the form."""
    pages = [[
        {"word_id": 111691, "word": "editar", "wordform": "editaron"},
        {"word_id": 130641, "word": "edit", "wordform": "editaron"},
    ]]
    monkeypatch.setattr(db, "SUPPORTED_LANGUAGES", ["es"])
    monkeypatch.setattr(db, "fetch_paginated_records",
                        lambda language, last, limit: pages.pop(0) if pages else [])
    db.initialize_cache()
    assert db.identify_word_id("editaron", "es") == 111691


@pytest.mark.parametrize('status', ['unverified', 'valid', 'flagged', 'invalid'])
def test_cache_query_uses_status_even_when_legacy_flag_disagrees(status):
    # Execute the actual RPC's relational query locally. Both legacy flag
    # values must produce the same result for an identical status.
    sql = (Path(__file__).parent / 'sql/word_status.sql').read_text()
    query = sql[sql.index('  with selected_words'):sql.index('end;\n$$;')]
    query = (query.replace('language_param', ':language')
             .replace('last_fetched_word_id', ':last').replace('fetch_limit', ':limit'))
    with sqlite3.connect(':memory:') as conn:
        conn.executescript('''
            create table words (id integer, root text, language text, status text);
            create table wordforms (word_id integer, form text, flagged boolean, status text);
            insert into words values (10, 'sacar', 'es', 'valid');
        ''')
        for legacy_flag in (0, 1):
            conn.execute('delete from wordforms')
            conn.execute('insert into wordforms values (10, ?, ?, ?)',
                         ('sacaran', legacy_flag, status))
            rows = conn.execute(query, {'language': 'es', 'last': None, 'limit': 1000}).fetchall()
            assert rows == [(10, 'sacar', None if status == 'invalid' else 'sacaran')]


def test_merged_root_does_not_shadow_the_valid_form_in_paginated_cache(db, monkeypatch):
    sql = (Path(__file__).parent / 'sql/word_status.sql').read_text()
    query = sql[sql.index('  with selected_words'):sql.index('end;\n$$;')]
    query = (query.replace('language_param', ':language')
             .replace('last_fetched_word_id', ':last').replace('fetch_limit', ':limit'))
    with sqlite3.connect(':memory:') as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript('''
            create table words (id integer, root text, language text, status text);
            create table wordforms (word_id integer, form text, flagged boolean, status text);
            insert into words values (1, 'junk', 'es', 'invalid');
            insert into words values (10, 'sacar', 'es', 'valid');
            insert into words values (20, 'sacaran', 'es', 'invalid');
            insert into words values (30, 'bueno', 'es', 'flagged');
            insert into wordforms values (1, 'junkform', 0, 'valid');
            insert into wordforms values (10, 'sacaran', 1, 'valid');
            insert into wordforms values (10, 'badform', 0, 'invalid');
        ''')

        def page(language, last, limit):
            return [dict(row) for row in conn.execute(query, {
                'language': language, 'last': last, 'limit': 1,
            })]

        monkeypatch.setattr(db, 'SUPPORTED_LANGUAGES', ['es'])
        monkeypatch.setattr(db, 'word_cache', {'es': {'words': {}, 'wordforms': {}}})
        monkeypatch.setattr(db, 'fetch_paginated_records', page)
        db.initialize_cache()

    assert db.identify_word_id('sacaran', 'es') == 10
    assert db.word_cache['es']['words'] == {'sacar': 10, 'bueno': 30}
    assert db.word_cache['es']['wordforms'] == {'sacaran': 10}


@pytest.mark.parametrize('status', ['unverified', 'valid', 'flagged', 'invalid'])
def test_fallback_checks_root_status_before_caching(db, monkeypatch, status):
    monkeypatch.setattr(db, 'word_cache', {'es': {'words': {}, 'wordforms': {}}})

    class Query:
        def select(self, columns):
            assert columns == 'id, status'
            return self

        def eq(self, column, value):
            assert (column, value) == ('language', 'es')
            return self

        def ilike(self, column, value):
            assert (column, value) == ('root', 'sacaran')
            return self

        def order(self, column):
            assert column == 'id'
            return self

        def limit(self, count):
            return self

        def execute(self):
            return SimpleNamespace(data=[{'id': 20, 'status': status}])

    monkeypatch.setattr(db.supabase, 'table', lambda name: Query())
    if status == 'invalid':
        with pytest.raises(ValueError, match='not found'):
            db.identify_word_id('sacaran', 'es')
        assert db.word_cache['es']['words'] == {}
        # Creation must still be able to see the rejected entry.
        assert db.find_dictionary_root('sacaran', 'es') == {'id': 20, 'status': 'invalid'}
    else:
        assert db.identify_word_id('sacaran', 'es') == 20
        assert db.word_cache['es']['words'] == {'sacaran': 20}


@pytest.mark.parametrize('status', ['unverified', 'valid', 'flagged', 'invalid'])
def test_new_entry_writes_status_and_matches_cache_visibility(db, monkeypatch, status):
    monkeypatch.setattr(db, 'word_cache', {'es': {'words': {}, 'wordforms': {}}})
    writes = []

    class Query:
        def __init__(self, table):
            self.table = table

        def insert(self, payload):
            writes.append((self.table, payload))
            return self

        upsert = insert

        def execute(self):
            return SimpleNamespace(data=[{'id': 10}])

    monkeypatch.setattr(db.supabase, 'table', Query)
    result = db.save_to_supabase('sacar', {'sacaran'}, 'es', status=status)
    assert writes == [
        ('words', {'root': 'sacar', 'source': None, 'language': 'es',
                   'translation': None, 'status': status}),
        ('wordforms', [{'word_id': 10, 'form': 'sacaran', 'status': status}]),
    ]
    assert result == (None if status == 'invalid' else 10)
    assert ('sacar' in db.word_cache['es']['words']) == (status != 'invalid')
    assert ('sacaran' in db.word_cache['es']['wordforms']) == (status != 'invalid')


@pytest.mark.parametrize('status', ['flagged', 'invalid'])
def test_new_form_does_not_overwrite_its_roots_audit(db, monkeypatch, status):
    monkeypatch.setattr(db, 'word_cache', {'es': {'words': {'sacar': 10}, 'wordforms': {}}})
    writes = []

    class Query:
        def insert(self, payload):
            writes.append(payload)
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    def table(name):
        assert name == 'wordforms', 'A form verdict must not change the root verdict'
        return Query()

    monkeypatch.setattr(db.supabase, 'table', table)
    result = db.add_wordform('sacaran', 10, 'es', status=status)
    assert writes == [{'word_id': 10, 'form': 'sacaran', 'status': status}]
    assert result == (None if status == 'invalid' else 10)
    assert ('sacaran' in db.word_cache['es']['wordforms']) == (status != 'invalid')


def test_a_new_root_does_not_take_over_an_existing_form(db, monkeypatch):
    monkeypatch.setattr(db, "word_cache", {"es": {"words": {}, "wordforms": {"editaron": 111691}}})
    class Insert:
        def insert(self, row):
            return self

        def update(self, row):
            return self

        def eq(self, *a):
            return self

        def execute(self):
            return None

    monkeypatch.setattr(db.supabase, "table", lambda name: Insert())
    db.add_wordform("editaron", 130641, "es", status='valid')
    assert db.identify_word_id("editaron", "es") == 111691
