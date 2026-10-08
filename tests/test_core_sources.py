"""Production source shutdown, including the reported Google News draft and backlog."""
import json
import os
import subprocess
import sys
import time

import pytest

import config
import db
import discovery
import source_policy
from sources import lfc_official, media_preview
from sources.base import SourceBatch

GOOGLE_URL = 'https://news.google.com/rss/articles/CBMiReportedExample?oc=5'
TWEET_URL = 'https://x.com/LFC/status/123456'
LFC_URL = 'https://www.liverpoolfc.com/news/new-contract'
BODY = 'Liverpool have agreed a new contract with Mohamed Salah following discussions between the player and the club.'


@pytest.fixture(autouse=True)
def core_mode(monkeypatch):
    monkeypatch.setattr(config, 'CORE_SOURCES_ONLY', True)
    monkeypatch.setattr(config, 'ENABLE_LFC', True)
    monkeypatch.setattr(config, 'ENABLE_TWITTER', True)
    monkeypatch.setattr(config, 'ENABLE_LFC_GOOGLE_FALLBACK', False)


def item(url=GOOGLE_URL, source='LFC Official', **extra):
    return dict(source=source, source_tag='Liverpool FC', url=url,
                title='Dylan Ngosang', body=BODY, **extra)


def test_actual_config_defaults_are_core_only():
    env = {k: v for k, v in os.environ.items() if not k.startswith(('ENABLE_', 'CORE_', 'OUTLET_RSS_'))}
    code = "import sys,types; sys.modules['dotenv']=types.SimpleNamespace(load_dotenv=lambda *a,**k:None); import config,json; print(json.dumps([config.CORE_SOURCES_ONLY,config.ENABLE_LFC_GOOGLE_FALLBACK,config.ENABLE_OUTLET_RSS,config.ENABLE_NEWS_SEARCH,config.OUTLET_RSS_SOURCES]))"
    result = subprocess.run([sys.executable, '-c', code], env=env, check=True, text=True, capture_output=True)
    assert json.loads(result.stdout) == [True, False, False, False, []]


def test_core_mode_overrides_stale_optional_true_settings(patched_main, monkeypatch):
    monkeypatch.setattr(config, 'CORE_SOURCES_ONLY', True)
    for flag in ('ENABLE_OUTLET_RSS', 'ENABLE_NEWS_SEARCH', 'ENABLE_BLUESKY', 'ENABLE_ROMANO'):
        monkeypatch.setattr(config, flag, True)
    assert {s[0] for s in patched_main._sources()} == {'twitter', 'lfc_official'}


@pytest.mark.parametrize('articles', [False, True])
@pytest.mark.parametrize('document', [None, '<html><main>No news links</main></html>'])
def test_official_failure_never_requests_google(monkeypatch, articles, document):
    monkeypatch.setattr(config, 'ENABLE_ARTICLES', articles)
    monkeypatch.setattr(lfc_official, 'http_get', lambda _: document)
    monkeypatch.setattr('sources.base.parse_rss', lambda *a, **k: pytest.fail('Google RSS must not run'))
    assert lfc_official.fetch() == []


def test_fallback_requires_both_explicit_opt_in_and_non_core_mode(monkeypatch):
    monkeypatch.setattr(config, 'ENABLE_LFC_GOOGLE_FALLBACK', True)
    calls = []
    monkeypatch.setattr('sources.base.parse_rss', lambda _: calls.append(1) or [{'title':'Liverpool update','link':GOOGLE_URL}])
    assert lfc_official._google_fallback() == []
    monkeypatch.setattr(config, 'CORE_SOURCES_ONLY', False)
    fallback = lfc_official._google_fallback()[0]
    assert calls == [1]
    assert fallback['source'] != 'LFC Official'


@pytest.mark.parametrize('url', [GOOGLE_URL, 'https://liverpoolfc.com.evil.org/news/fake',
                               'https://www.liverpoolfc.com/team/dylan', 'https://x.com/LFC',
                               'https://www.liverpoolfc.com/news/listing/mens-team-news',
                               'https://www.liverpoolfc.com/news/category/men',
                               'https://example.org/news', 'not a url'])
def test_source_labels_cannot_bypass_real_url_check(url):
    assert source_policy.disabled_reason(item(url))


@pytest.mark.parametrize('url', [LFC_URL, TWEET_URL, 'https://twitter.com/LFC/status/123',
                               'https://x.com/i/web/status/123'])
def test_real_official_news_and_tweets_remain_enabled(url):
    assert source_policy.disabled_reason(item(url)) is None


def test_current_official_cards_have_sibling_headings_and_no_navigation_news(monkeypatch):
    document = '''<nav><a href="/news/listing/mens-team-news">Men</a>
      <a href="/news/category/men">Men</a></nav>
      <article data-testid="article-card">
        <a href="/news/new-contract" aria-label="Liverpool confirm new contract"></a>
        <div><img src="https://cdn.example.org/player.jpg"></div>
        <div><a href="/news/category/men">Men</a><h3>Liverpool confirm new contract</h3>
          <p>Mohamed Salah signs a new Liverpool contract.</p>
          <time datetime="2026-10-08">Today</time></div>
      </article>'''
    monkeypatch.setattr(config, 'ENABLE_ARTICLES', False)
    monkeypatch.setattr(lfc_official, 'http_get', lambda _: document)
    received = lfc_official.fetch()
    assert len(received) == 1
    assert received[0]['title'] == 'Liverpool confirm new contract'
    assert received[0]['body'] == 'Mohamed Salah signs a new Liverpool contract.'
    assert received[0]['image'] == 'https://cdn.example.org/player.jpg'
    assert received[0]['published_at'] == '2026-10-08'


def test_accessibility_title_is_supported_without_inner_anchor_text(monkeypatch):
    monkeypatch.setattr(config, 'ENABLE_ARTICLES', False)
    monkeypatch.setattr(lfc_official, 'http_get', lambda _: '<article><a href="/news/new-contract" aria-label="Liverpool confirm new contract"></a></article>')
    assert lfc_official.fetch()[0]['title'] == 'Liverpool confirm new contract'


def test_disabled_backlog_is_preserved_before_story_grouping(tmp_db):
    bad = item(source_id='lfc_official', image='https://example.org/google-logo.png')
    good = item(TWEET_URL, source='Twitter', source_id='twitter')
    db.ingest_batch('lfc_official', SourceBatch([bad]))
    db.ingest_batch('twitter', SourceBatch([good]))
    rows = db.queue_items(5)
    assert [r['payload']['url'] for r in rows] == [TWEET_URL]
    assert db.get(db.make_key(bad))['status'] == 'source_disabled'
    assert db.get(db.make_key(bad))['payload']['body'] == BODY
    assert not rows[0]['payload'].get('image')
    assert db.count() == 2


def test_source_pause_survives_restart_and_can_resume_without_losing_retry(tmp_db, monkeypatch):
    bad = item(source='News search', source_id='news_search', translated={'body':'متن'})
    key = db.save(bad)
    db.stage_failed(key, 'send', 'temporary Telegram failure')
    before = db.get(key)
    db.apply_source_policy()
    db._conn.close()
    db._conn = None
    db.init()
    assert db.get(key)['status'] == 'source_disabled'
    monkeypatch.setattr(config, 'CORE_SOURCES_ONLY', False)
    monkeypatch.setattr(config, 'ENABLE_NEWS_SEARCH', True)
    db.apply_source_policy()
    after = db.get(key)
    assert after['status'] == 'retry_pending'
    assert after['retry_stage'] == 'send'
    assert after['retry_count'] == before['retry_count']
    assert after['error'] == before['error']


def test_existing_send_retry_never_contacts_telegram(patched_main, monkeypatch):
    bad = item(translated={'title':'دیلان','body':'دیلان — لیورپول'})
    key = db.save(bad)
    db.stage_failed(key, 'send', 'temporary failure')
    db._c().execute('UPDATE items SET next_retry_at=0 WHERE key=?', (key,))
    db._c().commit()
    monkeypatch.setattr(patched_main.tg, 'send_post', lambda *a, **k: pytest.fail('must not send'))
    assert patched_main.retry_pending_sends() == 0
    assert db.get(key)['status'] == 'source_disabled'


def test_disabled_items_cannot_be_forced_translated_or_published(patched_main, monkeypatch):
    bad = item(translated={'title':'دیلان','body':'دیلان — لیورپول'})
    key = db.save(bad, status='sent_admin', admin_msg=123)
    monkeypatch.setattr(patched_main.translate, 'translate', lambda *a: pytest.fail('must not translate'))
    assert patched_main.process_item(bad, force=True) is False
    assert patched_main.send_to_channel(key)[0] is False
    assert patched_main.approve(key, 'admin')[0] is False
    assert patched_main.tg.calls == []


def test_core_mode_blocks_discovery_even_if_search_flag_is_true(monkeypatch):
    monkeypatch.setattr(config, 'ENABLE_NEWS_SEARCH', True)
    monkeypatch.setattr(discovery, 'parse_rss', lambda *a, **k: pytest.fail('must not fetch'))
    assert not discovery.fetch_search(refresh=True).items


def test_google_preview_is_not_fetched_for_a_valid_tweet(monkeypatch):
    monkeypatch.setattr(config, 'ENABLE_AUTO_IMAGE', True)
    monkeypatch.setattr(config, 'ENABLE_TWITTER_MEDIA', True)
    monkeypatch.setattr(media_preview, 'http_get', lambda *a, **k: pytest.fail('Google logo must not fetch'))
    tweet = item(TWEET_URL, source='Twitter', linked_urls=[GOOGLE_URL])
    media_preview.enrich(tweet)
    assert tweet['image'] is None


def test_paused_news_is_not_pruned_or_trimmed(tmp_db):
    from scripts.maintenance.db_prune import prune
    key = db.save(item(), status='source_disabled')
    db._c().execute('UPDATE items SET created_at=? WHERE key=?', (time.time()-30*86400, key))
    db._c().commit()
    prune()
    assert db.get(key)['payload']['body'] == BODY
