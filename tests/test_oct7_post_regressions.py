"""Follow-up screenshot cases: stale live updates, greetings and translator refusals."""
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import config
import db
import formatter
import news_policy
import translate
import translation_quality
from sources.base import SourceBatch
from sources import twitter
from sources import fxembed

NOW = datetime(2026, 10, 7, 9, tzinfo=timezone.utc).timestamp()


def news(body, published=None, source='Twitter', url='https://example.test/1'):
    return {'source': source, 'source_tag': 'Asim', 'ingest_handle': '@Asim_LFC',
            'title': body, 'body': body, 'url': url, 'published_at': published}


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(time, 'time', lambda: NOW)


@pytest.mark.parametrize('text', ['Goodnight 🤧\n#LFC', 'Goodnight Liverpool', 'شب بخیر #لیورپول',
                                 '🌙 **Goodnight Liverpool**', '#LFC 👋 GOODNIGHT', 'شب‌بخیر لیورپول'])
def test_personal_greeting_never_uses_translation_or_admin_group(patched_main, monkeypatch, text):
    monkeypatch.setattr(patched_main.translate, 'translate', lambda *a: pytest.fail('greeting must not translate'))
    assert not patched_main.process_item(news(text))
    assert not patched_main.tg.calls


def test_greeting_with_actual_training_news_is_still_relevant():
    assert news_policy.decision(news('Good morning Liverpool. The first-team squad are training at AXA today.'))[0] == 'review'
    assert news_policy.decision(news('Good morning Liverpool. Talks over a new contract are continuing.'))[0] == 'review'


def test_two_month_old_full_time_is_kept_for_manual_review(clock, patched_main, monkeypatch):
    item = news('Full time: Liverpool 2-0 Ipswich', NOW - 60 * 86400)
    db.ingest_batch('twitter', SourceBatch([item]))
    monkeypatch.setattr(patched_main.translate, 'translate', lambda *a: pytest.fail('stale result must not translate'))
    news_policy.classify_queued()
    key = db.make_key(item)
    assert db.get(key)['status'] == 'awaiting_relevance'
    assert db.get(key)['payload']['published_at'] == item['published_at']
    assert not db.queue_items()
    assert not patched_main.process_item(item)
    assert not patched_main.tg.calls


def test_live_update_waiting_in_queue_becomes_manual_but_is_not_deleted(clock):
    item = news('Full time: Liverpool 2-0 Ipswich', NOW - 60 * 86400)
    key = db.save(item)
    db._c().execute('UPDATE items SET created_at=? WHERE key=?', (item['published_at'] + 60, key))
    db._c().commit()
    news_policy.classify_queued()
    assert db.get(key)['status'] == 'awaiting_relevance'
    assert db.get(key)['payload']['body'] == item['body']


def test_old_transfer_backlog_is_retained_and_shows_date_after_admin_confirmation(clock, patched_main):
    from admin_news import feedback
    item = news('Liverpool have agreed a deal to sign a new defender.', NOW - 60 * 86400)
    key = db.save(item)
    news_policy.classify_queued()
    assert db.get(key)['status'] == 'awaiting_relevance'
    feedback(key, True)
    assert patched_main.process_item(db.get(key)['payload'])
    caption = patched_main.tg.sent_messages[-1]
    assert '2026-08-08' in caption
    assert 'قدیمی' in caption


def test_fresh_at_discovery_transfer_keeps_processing_after_provider_outage(clock, patched_main):
    item = news('Liverpool have agreed a deal to sign a new defender.', NOW - 3 * 86400)
    key = db.save(item)
    db._c().execute('UPDATE items SET created_at=? WHERE key=?', (item['published_at'] + 60, key))
    db._c().commit()
    news_policy.classify_queued()
    assert db.get(key)['status'] == 'new'
    assert patched_main.process_item(db.get(key)['payload'])
    assert '2026-10-04' in patched_main.tg.sent_messages[-1]


def test_fresh_historical_article_and_unknown_date_are_not_discarded(clock):
    assert news_policy.decision(news('Liverpool look back at their title win in 2015.', NOW - 30))[0] == 'review'
    assert news_policy.decision(news('Liverpool won 2-0', 'not a date'))[0] == 'review'


def test_admin_link_retains_publication_time():
    entry = {'link': 'https://x.com/Asim_LFC/status/123', 'title': 'Liverpool won',
             'summary': 'Liverpool won', 'published': 'Tue, 06 Oct 2026 09:00:00 GMT', '_xscrape_media': []}
    assert twitter.build_tweet_item(entry, 'Asim_LFC')['published_at'] == entry['published']


def test_exact_shared_links_do_not_reach_automatic_translation(clock, patched_main, monkeypatch):
    examples = [
        ('PartedBeard', {'id': '2101613314635673952', 'text': 'sabah ereksiyonumuzun sebebi',
                         'created_timestamp': 1789898634, 'author': {'screen_name': 'ellocobielsaa'},
                         'quote': {'id': '2101612026866913313', 'text': '',
                                   'author': {'screen_name': 'sametic88'}, 'media': {'photos': []}}}),
        ('anfieldsociaI', {'id': '2095978975570940258', 'text': 'FT: Ipswich 0-2 Liverpool',
                          'created_timestamp': 1788555303, 'author': {'screen_name': 'anfieldsociaI'}}),
    ]
    monkeypatch.setattr(patched_main.translate, 'translate', lambda *a: pytest.fail('reported posts must not translate'))
    for handle, status in examples:
        item = twitter.build_tweet_item(fxembed._to_entry(status, handle), handle)
        assert not patched_main.process_item(item)
        assert db.get(db.make_key(item))['status'] == 'awaiting_relevance'
    assert not patched_main.tg.calls


@pytest.mark.parametrize('stamp', [float('nan'), float('inf'), 1e30, 'bad date'])
def test_invalid_dates_do_not_break_publication_or_relevance(stamp):
    item = news('Liverpool news', stamp)
    assert news_policy.decision(item)[0] == 'review'
    assert formatter.build_admin_caption(item, {'title': '', 'body': 'خبر لیورپول'})


@pytest.mark.parametrize('result', [
    {'title': 'خطای ورودی', 'body': 'متن ارسال‌شده، فاقد محتوای خبری فوتبال است و قابل ترجمه نمی‌باشد.'},
    {'title': 'ورودی نامعتبر', 'body': 'لطفاً متن معتبر برای ترجمه ارسال کنید.'},
    {'title': 'عدم امکان ترجمه', 'body': 'این متن قابل ترجمه نیست.'},
])
def test_persian_model_error_is_not_accepted_as_translation(result):
    assert not translate._valid_result(result)


def test_refusal_triggers_next_model_in_chain(monkeypatch):
    calls = []
    class Router:
        def completion(self, **kwargs):
            calls.append(kwargs['model'])
            data = ({'title': 'خطای ورودی', 'body': 'متن ارسال‌شده فاقد محتوای خبری فوتبال است و قابل ترجمه نمی‌باشد.'}
                    if kwargs['model'] == 'bad' else {'title': '', 'body': 'لیورپول پیروز شد.'})
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data, ensure_ascii=False)))])
    monkeypatch.setattr(translate, '_get_router', lambda: (Router(), ['bad', 'good']))
    monkeypatch.setattr(translate, '_deployments', lambda: ([], ['bad', 'good'], False))
    assert translate._translate_short(news('Liverpool won.'), review=False)['provider'] == 'good'
    assert calls == ['bad', 'good']


def test_title_only_similarity_cannot_claim_same_news_from_other_sources(clock):
    a = news('Liverpool win against Ipswich after scoring two goals in the second half.', NOW - 60, source='RSS')
    a.update(source_tag='Transfermarkt', title='Liverpool 2-0 Ipswich')
    db.save(a, status='sent_admin')
    b = news('I just watched the whole Fulham match. Liverpool have a serious tactical problem.', NOW, url='https://example.test/2')
    b['title'] = 'Liverpool'
    assert db.similar_sources(b) == []
    c = dict(b, title=a['title'])
    assert db.similar_sources(c) == []


def test_confirmed_story_sources_remain_available(clock):
    item = news('Liverpool have agreed a deal for a new defender and talks on personal terms will continue tomorrow.', NOW)
    db.save(dict(item, source_tag='A'), status='sent_admin')
    assert db.similar_sources(dict(item, url='https://example.test/2', source_tag='B')) == ['A']


def test_same_text_from_two_different_match_dates_is_not_same_story(clock):
    import discovery
    a = news('Liverpool beat Ipswich by two goals to nil after an impressive display at Anfield.', NOW)
    b = news(a['body'], NOW - 60 * 86400, url='https://example.test/2')
    assert not discovery.same_story(a, b)


def test_score_review_detects_reversed_winner_even_when_numbers_match():
    source = news('Full time: Liverpool 2-0 Ipswich')
    translated = {'title': 'پایان بازی: لیورپول ۲-۰ ایپسویچ', 'body': 'پایان بازی: ایپسویچ ۲-۰ لیورپول'}
    assert 'match score/team order requires review' in translation_quality.check(source, translated, {})
    translated['body'] = 'پایان بازی: ایپسویچ ۰-۲ لیورپول'
    assert 'match score/team order requires review' not in translation_quality.check(source, translated, {})


def test_ordinary_failure_quote_remains_valid():
    assert translate._valid_result({'title': 'اسلات درباره مشکل ویدیو', 'body': 'اسلات گفت: ویدیوی بازی در دسترس نبود.'})


def test_long_article_refusal_in_old_cache_is_retranslated(monkeypatch):
    import hashlib
    body = 'Liverpool won.\n\nLiverpool scored.'
    source = news(body)
    fingerprint = hashlib.sha256((source['title'] + body).encode()).hexdigest()
    source['_translation_chunks'] = {'fingerprint': fingerprint, 'parts': {
        '0': {'title': 'خطای ورودی', 'body': 'این متن قابل ترجمه نیست.', 'provider': 'old'}}}
    calls = []
    def translate_part(item):
        calls.append(item['body'])
        return {'title': '', 'body': 'لیورپول پیروز شد.', 'provider': 'new', 'quality_issues': []}
    monkeypatch.setattr(translate, '_translate_short', translate_part)
    result = translate._translate_long_article(source)
    assert calls and 'خطای ورودی' not in result['body']


def test_source_annotation_is_not_repeated_in_admin_footer():
    item = dict(news('Liverpool update'), original_source='@sametic88', original_source_tag='samet')
    caption = formatter.build_admin_caption(item, {'title': '', 'body': 'خبر لیورپول', 'provider': 'test'})
    assert caption.count('منبع اصلی') == 1
