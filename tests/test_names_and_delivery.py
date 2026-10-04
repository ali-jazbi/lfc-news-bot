import json
import re
from html import unescape

import db
import names
from telegram_text import split_html


def entity(qid='Q1', affiliation=True, fa='بازیکن آزمایشی'):
    claims = {'P31': [{'mainsnak': {'datavalue': {'value': {'id': 'Q5'}}}}]}
    if affiliation:
        claims['P54'] = [{'mainsnak': {'datavalue': {'value': {'id': 'QClub'}}}}]
    return {'labels': {'en': {'value': 'Test Player'}, 'fa': {'value': fa}},
            'aliases': {'en': [{'value': 'T. Player'}]}, 'claims': claims}


def test_lookup_requires_identity_not_similar_name(monkeypatch):
    def api(params):
        if params['action'] == 'wbsearchentities':
            return {'search': [{'id': 'Q1', 'label': 'Test Player'}]}
        return {'entities': {'Q1': entity(affiliation=False)}}
    monkeypatch.setattr(names, '_api', api)
    assert names.lookup('Test Player', 'QClub') is None
    monkeypatch.setattr(names, '_api', lambda params: {'search': [{'id': 'Q1', 'label': 'Test Player'}]}
                        if params['action'] == 'wbsearchentities' else {'entities': {'Q1': entity()}})
    assert names.lookup('Test Player', 'QClub')[1] == 'بازیکن آزمایشی'


def test_missing_persian_label_and_ambiguous_identity(monkeypatch):
    def api(params):
        if params['action'] == 'wbsearchentities':
            return {'search': [{'id': 'Q1', 'label': 'Test Player'}, {'id': 'Q2', 'label': 'Test Player'}]}
        return {'entities': {'Q1': entity(), 'Q2': entity()}}
    monkeypatch.setattr(names, '_api', api)
    assert names.lookup('Test Player', 'QClub') is None
    monkeypatch.setattr(names, '_api', lambda params: {'search': [{'id': 'Q1', 'label': 'Test Player'}]}
                        if params['action'] == 'wbsearchentities' else {'entities': {'Q1': entity(fa=None)}})
    assert names.lookup('Test Player', 'QClub') is None


def test_admin_approval_updates_shared_glossary(tmp_db):
    db._c().execute('INSERT INTO person_names (english,candidate,official_url) VALUES (?,?,?)',
                    ('Test Player', 'بازیکن پیشنهادی', 'https://www.liverpoolfc.com/teams/mens-team/test-player'))
    db._c().commit()
    assert 'Test Player' not in names.glossary()
    person_id = db._c().execute('SELECT id FROM person_names').fetchone()[0]
    names.approve(person_id, 'بازیکن آزمایشی')
    assert names.glossary()['Test Player'] == 'بازیکن آزمایشی'
    assert names.unknown_in('Test Player scored.') == []


def test_network_failure_retains_approved_names(tmp_db, monkeypatch):
    db._c().execute('INSERT INTO person_names (english,persian) VALUES (?,?)', ('Test Player', 'بازیکن'))
    db._c().commit()
    monkeypatch.setattr(names.requests, 'get', lambda *a, **k: (_ for _ in ()).throw(ConnectionError('offline')))
    names.refresh()
    assert names.glossary()['Test Player'] == 'بازیکن'


def test_html_continuations_preserve_text_entities_and_emoji():
    text = '<b>عنوان</b>\n<blockquote expandable>' + ('خبر &amp; جزئیات 🔴 ' * 800) + '</blockquote>'
    parts = split_html(text)
    assert len(parts) > 1
    assert all(len(p.encode('utf-16-le')) // 2 <= 3500 for p in parts)
    plain = lambda s: unescape(re.sub('<[^>]*>', '', s))
    assert ''.join(map(plain, parts)) == plain(text)
    assert all(p.count('<blockquote expandable>') == p.count('</blockquote>') for p in parts)


def test_failed_continuation_reports_send_failure(monkeypatch):
    from telegram_api import Telegram
    client = Telegram(token='test')
    calls = []
    def call(method, **params):
        calls.append(params)
        return {'message_id': 1} if len(calls) == 1 else None
    monkeypatch.setattr(client, 'call', call)
    assert client.send_message(1, 'خبر ' * 2000) is None
    assert len(calls) == 2


def test_unknown_name_lookup_is_cached_without_blocking_news(monkeypatch):
    names.remember_unknowns({'body': 'Test Player scored today.', 'url': 'https://example.test/news'})
    calls = []
    monkeypatch.setattr(names, 'lookup', lambda en: calls.append(en) or ('Q42', 'بازیکن تازه', []))
    names.refresh_unknowns()
    names.refresh_unknowns()
    assert calls == ['Test Player']
    assert 'Test Player' not in names.glossary()
    row = db._c().execute('SELECT * FROM person_names').fetchone()
    names.approve(row['id'], 'بازیکن تازه')
    assert names.glossary()['Test Player'] == 'بازیکن تازه'
