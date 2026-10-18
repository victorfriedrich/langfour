"""Reader classification must respect audit verdicts, not legacy flags."""

import sqlite3
from pathlib import Path

import pytest


@pytest.mark.parametrize('form_status', ['valid', 'invalid', 'flagged', 'unverified'])
@pytest.mark.parametrize('root_status', ['valid', 'invalid'])
@pytest.mark.parametrize('legacy_flag', [None, 0, 1])
def test_classification_uses_audit_status(form_status, root_status, legacy_flag):
    # Run the RPC's actual form-candidate query against local rows. Only the
    # schema prefix and outer LATERAL inputs need adapting for SQLite.
    sql = (Path(__file__).parent / 'sql/classify_words.sql').read_text()
    query = sql[sql.index('select wf.word_id, 2'):sql.index('        ) m')]
    query = (query.replace('public.', '').replace('i.token', ':token')
             .replace('language_filter', ':language'))
    with sqlite3.connect(':memory:') as conn:
        conn.executescript('''
            create table words (id integer, language text, status text);
            create table wordforms (word_id integer, form text, status text, flagged boolean);
        ''')
        conn.execute('insert into words values (10, ?, ?)', ('es', root_status))
        conn.execute('insert into wordforms values (10, ?, ?, ?)',
                     ('sacaran', form_status, legacy_flag))
        rows = conn.execute(query, {'token': 'Sacaran', 'language': 'es'}).fetchall()
        assert rows == ([(10, 2)] if form_status == root_status == 'valid' else [])
        assert conn.execute(query, {'token': 'Sacaran', 'language': 'de'}).fetchall() == []
