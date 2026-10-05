import json
import time

import pytest

import admin_news
import config
import db
import discovery
import news_policy
from sources.base import SourceBatch


BODY = ('Liverpool have agreed a new contract with Mohamed Salah following discussions '
        'between the player and the club this week. The announcement includes his commitment to the team.')


def news(n=1, source='Reporter', **extra):
    return dict(source=source, source_tag=source, url=f'https://example.org/{n}',
                title='Liverpool agree a new contract', body=BODY, **extra)


def test_reference_snapshot_does_not_ingest_until_admin_recovers(monkeypatch, tmp_db):
    from sources import outlet_rss
    monkeypatch.setattr(config, 'ENABLE_LFC', False)
    monkeypatch.setattr(config, 'ENABLE_OUTLET_RSS', True)
    monkeypatch.setattr(config, 'OUTLET_RSS_SOURCES', [])
    monkeypatch.setattr(config, 'ENABLE_NEWS_SEARCH', False)
    monkeypatch.setattr(outlet_rss, 'fetch', lambda limit: [news(1), news(2)])
    db.save(news(1), status='sent_admin')
    assert discovery.scan_missed()
    assert db.count() == 1
    missing = discovery.missed_candidates()
    assert [r['payload']['url'] for r in missing] == [news(2)['url']]
    key = discovery.recover(missing[0]['key'])
    assert db.get(key)['status'] == 'discovered'
    assert db.get(key)['payload']['admin_relevance'] == 'related'
    assert not discovery.missed_candidates()
    with pytest.raises(ValueError):
        discovery.recover(key)


def test_failed_or_rejected_reference_is_recoverable_and_attempts_reset(tmp_db):
    key = db.save(news(), status='rejected', admin_msg=24)
    db.stage_failed(key, 'translation', 'bad output')
    discovery.recover(key)
    row = db.get(key)
    assert row['retry_count'] == 0 and row['admin_msg'] == 24
    assert row['error'] is None
    assert news_policy.decision(row['payload'])[0] == 'review'


def test_missed_checks_age_only_at_discovery_and_preserves_unknown_dates(tmp_db):
    with db._lock, db._c():
        for n, stamp in ((1, time.time() - 3 * 86400), (2, 'unknown')):
            item = news(n, published_at=stamp)
            db._c().execute('INSERT INTO discovery_candidates VALUES (?,?,?,?,?)',
                            (db.make_key(item), json.dumps(item), time.time(), time.time(), 'missing'))
    assert [r['payload']['url'] for r in discovery.missed_candidates()] == [news(2)['url']]
    db.ingest_batch('rss', SourceBatch([news(1, published_at=time.time()-3*86400)]))
    assert db.queue_items(5)  # A received/ingested old item is never dropped by age.


def test_dismissed_snapshot_is_not_resurrected_by_refresh(monkeypatch, tmp_db):
    from sources import outlet_rss
    monkeypatch.setattr(config, 'ENABLE_LFC', False)
    monkeypatch.setattr(config, 'ENABLE_NEWS_SEARCH', False)
    monkeypatch.setattr(config, 'ENABLE_OUTLET_RSS', True)
    monkeypatch.setattr(config, 'OUTLET_RSS_SOURCES', [])
    monkeypatch.setattr(outlet_rss, 'fetch', lambda limit: [news()])
    discovery.scan_missed()
    db._c().execute("UPDATE discovery_candidates SET state='dismissed'")
    db._c().commit()
    discovery.scan_missed()
    assert not discovery.missed_candidates()


def test_identical_cross_source_body_is_one_card_and_keeps_media_and_raw_rows(tmp_db):
    a, b, c = news(1, 'A'), news(2, 'B', video_url='https://video.org/a.mp4'), news(3, 'C', image='https://image.org/a.jpg')
    db.ingest_batch('rss', SourceBatch([a, b, c]))
    rows = db.queue_items(5)
    assert len(rows) == 1 and db.count() == 3
    leader = rows[0]['payload']
    assert leader['video_url'] == b['video_url'] and leader['image'] == c['image']
    assert leader['video_source_url'] == b['url']
    assert len(leader['story_sources']) == 3
    assert db.get(db.make_key(b))['payload']['body'] == BODY
    assert db.get(db.make_key(b))['status'] == 'grouped'


def test_similar_titles_negations_amounts_and_rumours_stay_separate(tmp_db):
    items = [news(1, 'A'), news(2, 'B'), news(3, 'C'), news(4, 'D')]
    items[1]['body'] = 'Liverpool have not agreed a new contract. ' + BODY
    items[2]['body'] = BODY + ' The value is 5 million pounds.'
    items[3]['body'] = 'Liverpool could agree a contract. ' + BODY
    db.ingest_batch('rss', SourceBatch(items))
    assert len(db.queue_items(5)) == 4
    a, b = news(5, 'A'), news(6, 'B')
    b['body'] = 'Same headline but different reporting.'
    assert not discovery.same_story(a, b)


def test_late_matching_source_attaches_to_existing_admin_card_without_retranslation(tmp_db):
    a, b = news(1, 'A'), news(2, 'B')
    a['translated'] = {'body': 'ترجمهٔ تأییدشده'}
    key = db.save(a, status='sent_admin', admin_msg=35)
    db.ingest_batch('rss', SourceBatch([b]))
    assert not db.queue_items()
    row = db.get(key)
    assert row['admin_msg'] == 35 and row['payload']['translated'] == a['translated']
    assert len(row['payload']['story_sources']) == 2


def test_late_video_remains_a_separate_reviewable_card(tmp_db):
    a, b = news(1, 'A'), news(2, 'B', video_url='https://video.org/late.mp4')
    db.save(a, status='sent_admin')
    db.ingest_batch('rss', SourceBatch([b]))
    rows = db.queue_items()
    assert len(rows) == 1 and rows[0]['payload']['video_url'] == b['video_url']


def test_different_video_clips_do_not_hide_each_other_and_userbot_uses_video_source(patched_main, monkeypatch):
    main = patched_main
    import sys
    from types import SimpleNamespace
    a, b = news(1, 'A', video_url='https://video.org/1.mp4'), news(2, 'B', video_url='https://video.org/2.mp4')
    db.ingest_batch('rss', SourceBatch([a, b]))
    assert len(db.queue_items()) == 2
    requests = []
    ub = SimpleNamespace(is_configured=lambda: True,
                         download_and_forward_sync=lambda **kw: requests.append(kw) or True)
    monkeypatch.setitem(sys.modules, 'userbot_downloader', SimpleNamespace(get_downloader=lambda: ub))
    monkeypatch.setattr(config, 'ENABLE_USERBOT_VIDEOS', True)
    payload = news(3, 'A', video_url=b['video_url'], video_source_url=b['url'])
    assert main._send_final_post(-1, 'کپشن کامل', payload)
    assert requests[0]['tweet_url'] == b['url'] and requests[0]['caption'] == 'کپشن کامل'


def test_same_quote_with_different_speaker_or_currency_never_merges(tmp_db):
    a, b = news(1, 'A'), news(2, 'B')
    a['title'], b['title'] = 'Arne Slot: His reaction today', 'Mohamed Salah: His reaction today'
    assert not discovery.same_story(a, b)
    a['title'], b['title'] = 'Liverpool agree a £5m deal', 'Liverpool agree a €5m deal'
    assert not discovery.same_story(a, b)


def test_manual_merge_requires_matching_material_claim_and_blocks_old_publish_buttons(patched_main):
    main = patched_main
    a = news(1, 'A', translated={'title': 'خبر', 'body': 'متن'})
    b = news(2, 'B', translated={'title': 'خبر', 'body': 'متن'})
    ka, kb = db.save(a, status='sent_admin'), db.save(b, status='sent_admin')
    discovery.merge_stories(ka, kb)
    assert db.get(kb)['story_key'] == ka
    assert not main.send_to_channel(kb)[0]
    assert not main.approve(kb, -1)[0]
    c = news(3, 'C')
    c['body'] += ' No deal has been agreed.'
    kc = db.save(c)
    with pytest.raises(ValueError):
        discovery.merge_stories(ka, kc)


def test_temporary_source_requires_confirmation_and_expires(monkeypatch, tmp_db):
    from sources import twitter
    monkeypatch.setattr(config, 'TWITTER_ACCOUNTS', ['Known'])
    monkeypatch.setattr(config, 'TWITTER_TIER1', ['Known'])
    citations = [news(n) for n in (1, 2)]
    for item in citations:
        item.update(ingest_handle='@Known', original_source='@NewReporter')
    discovery.discover_sources(citations)
    discovery.discover_sources(citations)
    assert db._c().execute('SELECT COUNT(*) FROM source_citations').fetchone()[0] == 2
    assert not discovery.source_handles()
    discovery.set_source('NewReporter', days=7)
    assert 'newreporter' in twitter._accounts()[1]
    db._c().execute('UPDATE source_candidates SET expires_at=?', (time.time()-1,))
    db._c().commit()
    assert 'newreporter' not in twitter._accounts()[1]
    assert db.checkpoint_map('twitter') == {}


def test_untrusted_or_irrelevant_citations_do_not_suggest_sources(monkeypatch, tmp_db):
    monkeypatch.setattr(config, 'TWITTER_TIER1', ['Trusted'])
    monkeypatch.setattr(config, 'TWITTER_LFC_ONLY', [])
    a = news(1, ingest_handle='@Unknown', original_source='@NewReporter')
    b = dict(a, ingest_handle='@Trusted', title='Arsenal', body='Arsenal sign player')
    discovery.discover_sources([a, b])
    assert db._c().execute('SELECT COUNT(*) FROM source_candidates').fetchone()[0] == 0


def test_entity_relationships_override_glossary_and_targets_expire(monkeypatch, tmp_db):
    monkeypatch.setattr(config, 'GLOSSARY', {'Old Player': 'بازیکن سابق', 'OldAlias': 'بازیکن سابق'})
    with db._lock, db._c():
        for name, role, expiry in [('old player', 'former', 0), ('new player', 'current', 0),
                                   ('transfer person', 'target', time.time()+100), ('expired person', 'target', time.time()-1)]:
            db._c().execute('INSERT INTO news_entities VALUES (?,?,?,?,?)', (name, role, expiry, 'admin', time.time()))
    assert not news_policy._has_liverpool_context('OldAlias scored for Arsenal')
    assert news_policy._has_liverpool_context('New Player scored for his national team')
    assert news_policy._has_liverpool_context('Transfer Person deal update')
    assert not news_policy._has_liverpool_context('Expired Person deal update')
    assert not news_policy._has_liverpool_context('Transfer Person deal with Arsenal')


def test_search_rotates_current_and_targets_and_throttles_without_losing_items(monkeypatch, tmp_db):
    monkeypatch.setattr(config, 'ENABLE_NEWS_SEARCH', True)
    urls = []
    def fake(url, **kwargs):
        urls.append(url)
        return [{'title': f'Liverpool {i}', 'link': f'https://example.org/{i}', 'summary': BODY} for i in range(60)]
    monkeypatch.setattr(discovery, 'parse_rss', fake)
    with db._lock, db._c():
        db._c().execute("INSERT INTO news_entities VALUES ('new player','current',0,'official',?)", (time.time(),))
    batch = discovery.fetch_search(limit=5)
    assert len(batch.items) == 120 and len(urls) == 2
    assert not discovery.fetch_search().items
    assert len(urls) == 2
    db.ingest_batch('news_search', batch)
    assert db.count() == 60  # Duplicate URLs across topic feeds, every received identity saved.


def test_broken_search_is_reported_as_failure_not_successful_empty(monkeypatch, tmp_db):
    monkeypatch.setattr(config, 'ENABLE_NEWS_SEARCH', True)
    monkeypatch.setattr(discovery, 'parse_rss', lambda *a, **k: (_ for _ in ()).throw(ConnectionError('offline')))
    with pytest.raises(ConnectionError):
        discovery.fetch_search()
    assert any(r['consecutive_failures'] for r in db.list_source_health())
    assert discovery._meta('search_checked') is None


def test_search_keeps_original_publisher_and_removes_only_publisher_title_suffix(monkeypatch, tmp_db):
    monkeypatch.setattr(config, 'ENABLE_NEWS_SEARCH', True)
    monkeypatch.setattr(discovery, 'parse_rss', lambda *a, **k: [
        {'title': 'Liverpool agree deal - BBC Sport', 'link': 'https://news.google.com/article/1',
         'summary': 'Liverpool agree deal', 'publisher': 'BBC Sport', 'publisher_url': 'https://bbc.co.uk'}])
    item = discovery.fetch_search().items[0]
    assert item['source_tag'] == 'BBC Sport'
    assert item['title'] == 'Liverpool agree deal'
    assert item['publisher_url'] == 'https://bbc.co.uk'


def test_rss_parser_preserves_google_news_publisher_metadata():
    from sources.base import parse_rss
    raw = '<rss version="2.0"><channel><title>News</title><item><title>Liverpool agree deal - BBC Sport</title>'
    raw += '<link>https://news.google.com/articles/1</link><source url="https://bbc.co.uk">BBC Sport</source>'
    raw += '</item></channel></rss>'
    item = parse_rss('https://news.google.com/rss', raw=raw, strict=True)[0]
    assert item['publisher'] == 'BBC Sport' and item['publisher_url'] == 'https://bbc.co.uk'


def test_strict_rss_does_not_hide_network_or_html_error_pages(monkeypatch):
    from sources.base import parse_rss
    monkeypatch.setattr('sources.base.http_get', lambda *a, **k: None)
    with pytest.raises(ConnectionError):
        parse_rss('https://test.org/feed', strict=True)
    with pytest.raises(ValueError):
        parse_rss('https://test.org/feed', raw='<html>Access denied</html>', strict=True)


def test_account_telemetry_is_atomic_with_items_and_checkpoints(tmp_db):
    batch = SourceBatch([news()], {'a': 123}, [{'handle': '@a', 'received': 1, 'latest_at': 123}])
    db.ingest_batch('twitter', batch)
    db.ingest_batch('twitter', SourceBatch([], {}, [{'handle': 'a', 'received': 0}]))
    row = dict(db._c().execute('SELECT * FROM account_polls').fetchone())
    assert row['last_item_at'] == 123 and row['received'] == 1 and row['empty_streak'] == 1
    with pytest.raises(ValueError):
        db.ingest_batch('twitter', SourceBatch([news(2)], {'a': 'invalid'}, [{'handle': 'a', 'received': 1}]))
    assert db.count() == 1
    assert dict(db._c().execute('SELECT * FROM account_polls').fetchone()) == row


def test_queue_callbacks_acknowledge_first_and_feedback_blocks_publication(patched_main):
    main = patched_main
    key = db.save(news(translated={'body': 'متن خبر'}, editorial_decision='review'), status='sent_admin')
    cq = {'id': 'q', 'data': 'irr:' + key, 'from': {'id': 1},
          'message': {'message_id': 12, 'chat': {'id': -1}}}
    main.handle_callback(cq)
    assert main.tg.calls[0][0] == 'answer_callback'
    assert db.get(key)['status'] == 'rejected'
    assert db._c().execute('SELECT ai_decision FROM feedback ORDER BY id LIMIT 1').fetchone()[0] == 'review'
    assert not main.send_to_channel(key)[0]
    cq['data'] = 'rel:' + key
    main.handle_callback(cq)
    assert db.get(key)['status'] == 'discovered'
    assert db._c().execute('SELECT COUNT(*) FROM feedback').fetchone()[0] == 2


def test_commands_and_callbacks_are_admin_only(patched_main, monkeypatch):
    main = patched_main
    monkeypatch.setattr(config, 'ADMIN_USER_IDS', [7])
    main.handle_message({'text': '/sources watch NewReporter', 'chat': {'id': -1}, 'from': {'id': 8}})
    main.handle_callback({'id': 'q', 'data': 'swatch:NewReporter', 'from': {'id': 8},
                          'message': {'chat': {'id': -1}, 'message_id': 2}})
    assert not discovery.source_handles()
    assert any('اجازه' in m for m in main.tg.sent_messages)


def test_queue_pagination_and_errors_do_not_claim_items(patched_main):
    main = patched_main
    db.ingest_batch('rss', SourceBatch([news(n, 'A') for n in range(12)]))
    main.handle_message({'text': '/queue pending 2', 'chat': {'id': -1}, 'from': {'id': 1}})
    assert 'صفحهٔ 2' in main.tg.sent_messages[-1]
    assert db.pipeline_stats() == {'discovered': 12}
    main.handle_callback({'id': 'q', 'data': 'qpg:pending:invalid', 'from': {'id': 1},
                          'message': {'chat': {'id': -1}, 'message_id': 2}})
    assert db.pipeline_stats() == {'discovered': 12}


def test_grouped_raw_payload_survives_prune_and_restart(tmp_db):
    from scripts.maintenance.db_prune import prune
    db.ingest_batch('rss', SourceBatch([news(1, 'A'), news(2, 'B')]))
    leader = db.queue_items()[0]
    db.set_status(leader['key'], 'published')
    db._c().execute('UPDATE items SET created_at=?', (time.time()-30*86400,))
    db._c().commit()
    prune()
    db._conn.close()
    db._conn = None
    db.init()
    assert db.count() == 2
    assert db.get(db.make_key(news(2, 'B')))['payload']['body'] == BODY


def test_unknown_timezone_is_preserved_and_account_case_does_not_double_poll(monkeypatch, tmp_db):
    from sources import twitter
    assert discovery.published_time('2026-01-01T10:00:00') is None
    monkeypatch.setattr(config, 'TWITTER_ACCOUNTS', ['NewReporter'])
    monkeypatch.setattr(config, 'TWITTER_TIER1', [])
    discovery.set_source('newreporter')
    assert twitter._accounts()[1] == ['NewReporter']


def test_translation_trace_records_invalid_first_model_and_successful_fallback(monkeypatch):
    import translate
    from types import SimpleNamespace
    monkeypatch.setattr(translate, '_deployments', lambda: ([], [], False))
    monkeypatch.setattr(translate, '_quality_review', lambda item, data, semantic=True: data)
    monkeypatch.setattr(translate.health, 'record_fail', lambda *a, **k: None)
    monkeypatch.setattr(translate.health, 'record_ok', lambda *a, **k: None)
    class Router:
        def completion(self, **kwargs):
            content = 'bad output' if kwargs['model'] == 'first' else json.dumps({'body': 'خبر کوتاه لیورپول', 'title': ''})
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    monkeypatch.setattr(translate, '_get_router', lambda: (Router(), ['first', 'second']))
    item = news()
    result = translate._translate_short(item)
    assert result
    assert [a['outcome'] for a in result['translation_attempts']] == ['error', 'ok']
    assert result['translation_attempts'][0]['provider'] == 'first'
    assert 'invalid' in result['translation_attempts'][0]['error']


def test_failed_translation_trace_is_saved_for_admin_callback(patched_main, monkeypatch):
    main = patched_main
    def failure(item):
        item['translation_attempts'] = [{'provider': 'model', 'outcome': 'error', 'error': 'rate limit'}]
        return None
    monkeypatch.setattr(main.translate, 'translate', failure)
    item = news()
    assert not main.process_item(item)
    key = db.make_key(item)
    assert db.get(key)['payload']['translation_attempts'][0]['error'] == 'rate limit'
    main.handle_callback({'id': 'q', 'data': 'chain:' + key, 'from': {'id': 1},
                          'message': {'message_id': 2, 'chat': {'id': -1}}})
    assert 'rate limit' in main.tg.sent_messages[-1]


def test_chain_report_explains_skipped_slots_without_credentials(monkeypatch):
    import translate
    monkeypatch.setattr(config, 'TRANSLATE_ORDER', ['llm1', 'llm2', 'llm13', 'translate'])
    monkeypatch.setattr(config, 'LLM_SLOTS', {
        'llm1': {'name': 'audio', 'model': 'whisper-large-v3', 'key': 'secret-value', 'base_url': 'https://api.test'},
        'llm2': {'name': 'missing', 'model': 'chat', 'key': '', 'base_url': 'https://api.test'},
    })
    report = translate.chain_report()
    assert 'گفت‌وگوی متنی نیست' in report and 'تنظیم ناقص' in report and 'llm13' in report
    assert 'secret-value' not in report and 'https://api.test' not in report


def test_existing_database_is_backed_up_before_discovery_migration(tmp_db):
    from pathlib import Path
    db.save(news(), status='sent_admin', admin_msg=22)
    db._c().execute('DROP TABLE discovery_candidates')
    db._c().commit()
    db._conn.close()
    db._conn = None
    db.init()
    assert list((Path(config.DB_PATH).parent / 'backups').glob('pre-pipeline-*.db'))
    assert db.get(db.make_key(news()))['admin_msg'] == 22
