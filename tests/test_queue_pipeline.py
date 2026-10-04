import json
import time
import pytest

import config
import db
from sources.base import SourceBatch


def item(index, account='a', **values):
    return dict(source='Twitter', source_tag='Reporter', handle='@' + account,
                ingest_handle='@' + account, url=f'https://x.com/{account}/status/{index}',
                title='Liverpool new contract', body='Liverpool have agreed a new contract.', **values)


def test_sixty_received_items_survive_processing_limit_and_restart(tmp_db):
    received = [item(i, 'a' if i < 30 else 'b') for i in range(60)]
    assert db.ingest_batch('twitter', SourceBatch(received, {'a': 100, 'b': 100})) == 60
    first = db.queue_items(5)
    assert len(first) == 5
    assert {r['payload']['handle'] for r in first} == {'@a', '@b'}
    for row in first[:3]:
        db.set_status(row['key'], 'sent_admin')
    db._conn.close()
    db._conn = None
    db.init()
    processed = 3
    while rows := db.queue_items(5):
        for row in rows:
            db.set_status(row['key'], 'sent_admin')
            processed += 1
    assert processed == 60
    assert db.checkpoint_map('twitter') == {'a': 100, 'b': 100}


def test_batch_failure_rolls_back_both_payload_and_checkpoint(tmp_db):
    with pytest.raises((TypeError, ValueError)):
        db.ingest_batch('twitter', SourceBatch([item(1), item(2, raw=object())], {'a': 100}))
    assert db.count() == 0
    assert db.checkpoint_map('twitter') == {}


def test_checkpoint_failure_rolls_back_valid_payload(tmp_db):
    with pytest.raises(ValueError):
        db.ingest_batch('twitter', SourceBatch([item(1)], {'a': 'bad'}))
    assert db.count() == 0


def test_duplicate_front_does_not_starve_new_items(tmp_db):
    old = item(1)
    db.save(old, status='sent_admin')
    assert db.ingest_batch('twitter', SourceBatch([old] * 10 + [item(2)])) == 1
    assert [r['payload']['url'] for r in db.queue_items(5)] == [item(2)['url']]


def test_upsert_preserves_creation_message_and_attempts(tmp_db):
    news = item(1)
    key = db.save(news, status='sent_admin', admin_msg=42)
    db.mark_attempt(key, 'retry_pending', error='old', retry=True)
    before = db.get(key)
    db.save(dict(news, translated={'body': 'متن'}), status='new')
    after = db.get(key)
    assert after['created_at'] == before['created_at']
    assert after['admin_msg'] == 42
    assert after['retry_count'] == 1


def test_round_robin_continues_across_cycles(tmp_db):
    db.ingest_batch('twitter', SourceBatch([item(i * 10 + n, str(i)) for i in range(9) for n in range(3)]))
    first = db.queue_items(5)
    second = db.queue_items(5)
    assert len({r['payload']['handle'] for r in first + second}) == 9


def test_stage_retry_finishes_at_three_and_can_be_reset(tmp_db):
    key = db.save(item(1))
    for attempt in range(3):
        db.stage_failed(key, 'translation', 'provider down')
    assert db.get(key)['status'] == 'failed'
    assert db.get(key)['retry_count'] == 3
    assert not db.queue_items()
    db.reset_retry(key)
    assert len(db.queue_items()) == 1


def test_prune_preserves_all_unfinished_states(tmp_db):
    from scripts.maintenance.db_prune import prune
    for index, status in enumerate(db.QUEUE_STATUSES):
        db.save(item(index), status=status)
    db._c().execute('UPDATE items SET created_at=?', (time.time() - 30 * 86400,))
    db._c().commit()
    prune()
    assert db.count() == len(db.QUEUE_STATUSES)
    assert all(json.loads(r[0])['body'] for r in db._c().execute('SELECT payload FROM items'))


def test_legacy_translation_failure_is_migrated_once(tmp_db):
    key = db.save(item(1), status='skipped')
    db.mark_attempt(key, 'skipped', error='translation chain failed')
    db._c().execute("DELETE FROM pipeline_meta WHERE key='queue_v1'")
    db._c().commit()
    db._conn.close()
    db._conn = None
    db.init()
    assert db.get(key)['status'] == 'discovered'
    db.set_status(key, 'sent_admin')
    db._conn.close()
    db._conn = None
    db.init()
    assert db.get(key)['status'] == 'sent_admin'


def test_no_hermes_client_used_for_legacy_cycle(patched_main, monkeypatch):
    main = patched_main
    monkeypatch.setattr(config, 'MAX_ITEMS_PER_CYCLE', 5)
    monkeypatch.setattr(main.time, 'sleep', lambda _: None)
    monkeypatch.setattr(main, 'collect', lambda: [item(i) for i in range(60)])
    monkeypatch.setattr(main, 'maybe_prune', lambda: None)
    monkeypatch.setattr(main, '_get_editor', lambda: pytest.fail('Hermes was called'))
    assert main.run_cycle() == 5
    assert db.count() == 60
    assert db.pipeline_stats()['discovered'] == 55


def test_failed_send_attempts_consume_cycle_capacity(patched_main, monkeypatch):
    main = patched_main
    monkeypatch.setattr(config, 'MAX_ITEMS_PER_CYCLE', 5)
    monkeypatch.setattr(main, 'maybe_prune', lambda: None)
    monkeypatch.setattr(main, 'collect', lambda: [item(i) for i in range(60)])
    monkeypatch.setattr(db, 'retryable_items', lambda limit: [None] * 5)
    monkeypatch.setattr(main, 'retry_pending_sends', lambda limit: 0)
    monkeypatch.setattr(main, 'process_item', lambda *a, **k: pytest.fail('cycle budget exceeded'))
    assert main.run_cycle() == 0
    assert db.pipeline_stats()['discovered'] == 60
