"""Regression cases from the October 6 admin screenshots and service logs."""
import json
import time
from types import SimpleNamespace

import pytest

import config
import health
import news_policy
import translate


def tweet(text, handle='PartedBeard'):
    return {'title': text, 'body': text, 'source': 'Twitter', 'ingest_handle': handle,
            'url': 'https://example.test/' + str(abs(hash(text)))}


@pytest.mark.parametrize('text,handle', [
    ('Republic of Ireland players lower their heads during the Israeli anthem.', 'LewisSteele_'),
    ('Belgium vs Turkey. Arda Guler is outstanding; Turkey defensively are naive.', 'PartedBeard'),
    ('Raphinha has signed a new Barcelona contract until 2030. Here we go.', 'FabrizioRomano'),
    ("We're back tonight 👀", 'Asim_LFC'),
    ('Mancini on Italy: Roma is the role model. Calafiori is a leader.', 'DiMarzio'),
])
def test_screenshot_stories_are_rejected_despite_account_identity(text, handle):
    assert news_policy.decision(tweet(text, handle))[0] == 'reject'


def test_ambiguous_short_post_is_held_even_on_club_specific_account():
    assert news_policy.decision(tweet('9 games of mine', 'Asim_LFC'))[0] == 'hold'


@pytest.mark.parametrize('text', [
    'Liverpool are interested in Arda Guler; Real Madrid want to keep him.',
    'Florian Wirtz scores for Germany.',
    'I was close to joining Liverpool in 2016, says Mbappe.',
    'Liverpool won against Arsenal. Watch the analysis.',
])
def test_real_liverpool_links_and_short_player_news_survive(text):
    assert news_policy.decision(tweet(text))[0] == 'review'


def test_journalist_name_in_glossary_does_not_establish_relevance(monkeypatch):
    monkeypatch.setattr(config, 'GLOSSARY', {'Lewis Steele': 'لوئیس استیل'})
    assert news_policy.decision(tweet('Lewis Steele: Ireland players react to Israeli anthem.'))[0] == 'reject'


def test_backlog_is_classified_before_translation_capacity(tmp_db, monkeypatch):
    import db
    from sources.base import SourceBatch
    unknown = tweet('9 games of mine', 'Asim_LFC')
    rival = tweet('Raphinha signs for Barcelona', 'FabrizioRomano')
    relevant = tweet('Liverpool won 2-0', 'LFC')
    db.ingest_batch('twitter', SourceBatch([unknown, rival, relevant]))
    news_policy.classify_queued()
    assert db.get(db.make_key(unknown))['status'] == 'awaiting_relevance'
    assert db.get(db.make_key(rival))['status'] == 'rejected'
    assert db.get(db.make_key(unknown))['payload']['body'] == unknown['body']
    assert [r['key'] for r in db.queue_items(5)] == [db.make_key(relevant)]


def test_hold_can_be_confirmed_by_admin_and_survives_cleanup(tmp_db):
    import db
    import admin_news
    from scripts.maintenance.db_prune import prune
    item = tweet('9 games of mine')
    key = db.save(item)
    news_policy.classify_queued()
    db._c().execute('UPDATE items SET created_at=?', (time.time() - 30 * 86400,))
    db._c().commit()
    prune(keep_days=1, trim_hours=1)
    assert db.get(key)['payload']['body'] == item['body']
    admin_news.feedback(key, True)
    assert db.get(key)['status'] == 'discovered'
    assert news_policy.decision(db.get(key)['payload'])[0] == 'review'


def test_provider_down_and_recovery_never_notify_admins():
    notices = []
    health.set_notifier(notices.append)
    for _ in range(4):
        health.record_fail('glm', '429 overloaded')
    health.record_ok('glm')
    assert notices == []


def test_server_retry_time_is_respected_without_six_hour_escalation(monkeypatch):
    monkeypatch.setattr(health.time, 'time', lambda: 1000)
    health.record_fail('groq', 'RateLimitError: Please try again in 5m4.992s.')
    assert health.stats('groq')['cooldown_until'] == pytest.approx(1304.992)
    assert not health.is_available('groq')
    with health.provider_slot('groq') as allowed:
        assert not allowed
    assert health.stats('groq')['fail'] == 1


def test_old_health_cooldowns_are_migrated_without_losing_counters(tmp_path):
    state = {'providers': {'groq': dict(health._blank(), ok=218, fail=232, streak=20,
                                       cooldown_until=time.time() + 21600)}, 'sources': {}, 'counters': {'received': 82615}}
    with open(health.STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f)
    health.load()
    assert health.is_available('groq')
    assert health.stats('groq')['ok'] == 218
    assert health._state['counters']['received'] == 82615
    backups = list((tmp_path / 'backups').glob('pre-provider-health-*.json'))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding='utf-8'))['providers']['groq']['streak'] == 20
    health.record_fail('groq', '429 rate limit')
    health.load()
    assert not health.is_available('groq')
    assert len(list((tmp_path / 'backups').glob('pre-provider-health-*.json'))) == 1


def test_failed_translation_migration_is_backed_up_and_runs_once(tmp_db, tmp_path):
    import sqlite3
    import db
    failed = db.save(tweet('Liverpool won.'))
    pending = db.save(tweet('Liverpool injury update.'))
    payload = db.get(failed)['payload']
    payload['translation_attempts'] = [{'provider': 'groq', 'outcome': 'error'}]
    db.update_payload(failed, payload)
    db.set_admin_msg(pending, 42, status=db.STATUS_PENDING_ADMIN)
    c = db._c()
    c.execute("UPDATE items SET status='failed',error='translation chain failed',"
              "retry_stage='translation',retry_count=3 WHERE key=?", (failed,))
    c.execute("DELETE FROM pipeline_meta WHERE key='translation_wait_v2'")
    c.commit()
    discovered_at = db.get(failed)['created_at']
    c.close()
    db._conn = None
    db.init()
    row = db.get(failed)
    assert row['status'] == 'retry_pending' and row['retry_count'] == 0
    assert row['payload'] == payload and row['created_at'] == discovered_at
    assert db.get(pending)['status'] == db.STATUS_PENDING_ADMIN
    assert db.get(pending)['admin_msg'] == 42
    recovered_backups = []
    for path in (tmp_path / 'backups').glob('pre-provider-queue-*.db'):
        with sqlite3.connect(path) as backup:
            result = backup.execute('SELECT status,retry_count FROM items WHERE key=?', (failed,)).fetchone()
            if result:
                recovered_backups.append(result)
    assert recovered_backups == [('failed', 3)]
    # A later real content failure is not silently revived on each restart.
    c = db._c()
    c.execute("UPDATE items SET status='failed',retry_count=3 WHERE key=?", (failed,))
    c.commit()
    c.close()
    db._conn = None
    db.init()
    assert db.get(failed)['status'] == 'failed'


def test_google_does_not_request_the_same_tweet_twice(monkeypatch):
    import sys
    requests = []
    monkeypatch.setitem(sys.modules, 'deep_translator', SimpleNamespace(GoogleTranslator=lambda **k: object()))
    monkeypatch.setattr(translate, '_google_translate', lambda tr, text: requests.append(text) or 'ویرتز گل زد.')
    result = translate._deep_translate(tweet('Wirtz scored.'))
    assert requests == ['Wirtz scored.']
    assert result['title'] == result['body'] == 'ویرتز گل زد.'


def response(value):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value, ensure_ascii=False)))])


def test_translation_and_qc_share_gate_and_provider_identity(monkeypatch):
    calls = []
    class Router:
        def completion(self, **kwargs):
            calls.append(kwargs['model'])
            if kwargs['model'] == 'limited':
                raise RuntimeError('429 rate limit')
            if len(calls) == 2:
                result = response({'title': '', 'body': 'لیورپول توافق نکرد.'})
                result._hidden_params = {'model_id': 'opaque-router-id'}
                return result
            return response({'ok': True, 'issues': []})
    monkeypatch.setattr(translate, '_get_router', lambda: (Router(), ['limited', 'good']))
    monkeypatch.setattr(translate, '_deployments', lambda: ([], [], False))
    result = translate.translate({'body': 'Liverpool have not agreed.'})
    assert calls == ['limited', 'good', 'good']
    assert result['provider'] == 'good'
    assert health.stats('limited')['fail'] == 1
    assert health.stats('good')['ok'] == 2


def test_all_unavailable_providers_are_not_called_or_counted_as_failed_news(monkeypatch):
    class Router:
        def completion(self, **kwargs):
            pytest.fail('cooling-down provider called')
    monkeypatch.setattr(translate, '_get_router', lambda: (Router(), ['groq']))
    monkeypatch.setattr(translate, '_deployments', lambda: ([], [], True))
    health.record_fail('groq', '429 rate limit')
    health.record_fail('مترجم گوگل', 'too many requests')
    monkeypatch.setattr(translate, '_deep_translate', lambda *a: pytest.fail('cooling-down Google called'))
    item = {'body': 'Liverpool won.'}
    assert translate.translate(item) is None
    assert item['translation_failure_kind'] == 'provider_unavailable'
    assert all(a['outcome'] == 'waiting' for a in item['translation_attempts'])
    assert health._state['counters'].get('chain_failed', 0) == 0


def test_service_outage_does_not_spend_item_retry_budget(patched_main, monkeypatch, sample_item):
    import main
    import db
    def unavailable(item):
        item['translation_failure_kind'] = 'provider_unavailable'
        item['translation_retry_at'] = time.time() + 180
        return None
    monkeypatch.setattr(main.translate, 'translate', unavailable)
    for _ in range(4):
        main.process_item(sample_item)
    row = db.get(db.make_key(sample_item))
    assert row['status'] == 'retry_pending'
    assert row['retry_count'] == 0
    assert row['next_retry_at'] > time.time()


def test_collection_continues_without_claiming_translation_when_outage(patched_main, monkeypatch, sample_item):
    import main
    import db
    monkeypatch.setattr(main, 'collect', lambda: [sample_item])
    monkeypatch.setattr(main.translate, 'providers_available', lambda: False)
    monkeypatch.setattr(main, 'process_item', lambda *a, **k: pytest.fail('claimed during outage'))
    assert main.run_cycle() == 0
    assert db.get(db.make_key(sample_item))['status'] == 'discovered'


def test_mixed_mapping_output_is_invalid_but_short_persian_is_valid():
    assert not translate._valid_result({'body': '* "Belgium vs Turkey" -> "بلژیک برابر ترکیه"\nArda Guler is outstanding surrounded by mediocre Turkish players.'})
    assert translate._valid_result({'body': 'ویرتز درخشید.'})


def test_prompt_glossary_and_review_payload_do_not_include_unrelated_metadata(monkeypatch):
    monkeypatch.setattr(translate.person_names, 'glossary', lambda: {'Florian Wirtz': 'فلوریان ویرتز', 'Raphinha': 'رافینیا'})
    source = {'title': '', 'body': 'Florian Wirtz scores.', 'images': ['unused-media-secret'],
              'translation_attempts': [{'error': 'irrelevant-history'}]}
    prompt = translate._build_messages(source)[0]['content']
    assert 'فلوریان ویرتز' in prompt and 'Raphinha' not in prompt
    requests = []
    class Router:
        def completion(self, **kwargs):
            requests.append(kwargs)
            return response({'ok': True, 'issues': []})
    monkeypatch.setattr(translate, '_get_router', lambda: (Router(), ['good']))
    translate._review_call(source, {'title': '', 'body': 'ویرتز گل زد.', 'translation_attempts': source['translation_attempts']})
    payload = requests[0]['messages'][1]['content']
    assert 'unused-media-secret' not in payload and 'irrelevant-history' not in payload
