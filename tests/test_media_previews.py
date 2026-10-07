"""Regression coverage for the supplied LFC/Paul Joyce examples, without network."""
import pytest

import config
import db
from sources import fxembed, lfc_official, media_preview, twitter

LFC_URL = 'https://www.liverpoolfc.com/news/lucas-leiva-opens-liverpool-fcs-third-retail-store-south-africa'
STORE_IMAGE = 'https://backend.liverpoolfc.com/sites/default/files/styles/lg/public/2026-10/lfc-south-africa-store-051026_56713802541bee279d7cf316de9260b1.jpg?itok=C5uA2fF-'
TIMES_URL = 'https://www.thetimes.com/sport/football/article/cody-gakpo-liverpool-transfer-manchester-city-spurs-netherlands-7zz5vr3zl'
GAKPO_IMAGE = 'https://www.thetimes.com/imageserver/image/eea7b788-4958-4a41-9022-f692d6fa19de.jpg?strip=all&format=webp&resize=1200'


def test_official_listing_extracts_noscript_image_without_full_article(monkeypatch):
    listing = '''<div><a href="/news/lucas-leiva-opens-liverpool-fcs-third-retail-store-south-africa">
      <img src="data:image/gif;base64,blank"><noscript><img src="/small.webp"
      srcset="/large.webp 1680w, /small.webp 576w"></noscript>
      <h3>Lucas Leiva opens Liverpool FC's third retail store in South Africa</h3></a></div>'''
    calls = []
    monkeypatch.setattr(lfc_official, 'http_get', lambda url: calls.append(url) or listing)
    monkeypatch.setattr(config, 'ENABLE_ARTICLES', False)
    item = lfc_official.fetch()[0]
    assert item['image'] == 'https://www.liverpoolfc.com/large.webp'
    assert item['images'] == [item['image']]
    assert calls == [config.LFC_NEWS_URL]


@pytest.mark.parametrize('prop', ['og:image', 'twitter:image', 'article:image'])
def test_article_metadata_supplies_the_image_when_listing_has_none(monkeypatch, prop):
    monkeypatch.setattr(media_preview, 'http_get', lambda *a, **k: f'<meta property="{prop}" content="{STORE_IMAGE}">')
    item = {'source': 'LFC Official', 'url': LFC_URL, 'image': 'data:image/gif;base64,blank'}
    media_preview.enrich(item)
    assert item['image'] == STORE_IMAGE
    assert item['images'] == [STORE_IMAGE]
    assert item['image_source_url'] == LFC_URL


def test_paul_joyce_link_image_survives_text_cleaning_and_restart(patched_main, monkeypatch):
    status = {'id': '2103517340897771521', 'text': 'An interview with Cody Gakpo.\n' + TIMES_URL,
              'author': {'name': 'Paul Joyce', 'screen_name': '_pauljoyce'}}
    entry = fxembed._to_entry(status, '_pauljoyce')
    item = twitter.build_tweet_item(entry, '_pauljoyce')
    assert TIMES_URL not in item['body']
    assert item['linked_urls'] == [TIMES_URL]
    calls = []
    monkeypatch.setattr(media_preview, 'http_get', lambda url, **k: calls.append(url) or f'<meta property="og:image" content="{GAKPO_IMAGE}">')
    sent = []
    original = patched_main.tg.send_post
    def capture(*args, **kwargs):
        sent.append(kwargs.get('image'))
        return original(*args, **kwargs)
    monkeypatch.setattr(patched_main.tg, 'send_post', capture)
    key = db.save(item)
    db._conn.close()
    db._conn = None
    db.init()
    assert patched_main.process_item(db.get(key)['payload'], force=True)
    assert calls == [TIMES_URL]
    assert sent == [GAKPO_IMAGE]
    assert db.get(key)['payload']['image'] == GAKPO_IMAGE


def test_quote_album_is_preserved_alongside_own_photo(monkeypatch):
    monkeypatch.setattr(config, 'ENABLE_TWITTER_MEDIA', True)
    own = 'https://pbs.twimg.com/media/own.jpg'
    quote = ['https://pbs.twimg.com/media/quote1.jpg', 'https://pbs.twimg.com/media/quote2.jpg']
    entry = fxembed._to_entry({'id': '12', 'text': 'Liverpool news', 'media': {'photos': [{'url': own}]},
                              'quote': {'id': '11', 'text': 'Liverpool update', 'author': {'screen_name': 'LFC'},
                                        'media': {'photos': [{'url': u} for u in quote]}}}, 'reporter')
    item = twitter.build_tweet_item(entry, 'reporter')
    assert item['images'] == [own] + quote
    assert item['image'] == own


def test_quote_only_album_reaches_telegram(patched_main, monkeypatch):
    quote = ['https://pbs.twimg.com/media/quote1.jpg', 'https://pbs.twimg.com/media/quote2.jpg']
    entry = fxembed._to_entry({'id': '12', 'text': 'Liverpool news',
                              'quote': {'id': '11', 'text': 'Liverpool update', 'author': {'screen_name': 'LFC'},
                                        'media': {'photos': [{'url': u} for u in quote]}}}, 'reporter')
    item = twitter.build_tweet_item(entry, 'reporter')
    assert item['images'] == quote
    assert patched_main.process_item(item)
    assert any(call[:4] == ('send_media_group', config.ADMIN_CHAT_ID, 2, 'photo') for call in patched_main.tg.calls)
    assert db.get(db.make_key(item))['payload']['images'] == quote


def test_quote_link_preview_and_xscrape_card_are_supported(monkeypatch):
    entry = {'link': 'https://x.com/report/status/12', 'title': 'Liverpool', 'summary': 'Liverpool',
             '_xscrape_media': [], '_xscrape_quoted': {'text': 'Cody Gakpo ' + TIMES_URL, 'card_image': GAKPO_IMAGE}}
    item = twitter.build_tweet_item(entry, 'report')
    assert item['image'] == GAKPO_IMAGE
    assert item['images'] == [GAKPO_IMAGE]
    assert item['linked_urls'] == [TIMES_URL]
    monkeypatch.setattr(media_preview, 'http_get', lambda *a, **k: pytest.fail('existing card must not fetch again'))
    media_preview.enrich(item)


def test_quoted_video_is_not_used_as_a_photo():
    entry = {'link': 'https://x.com/report/status/12', 'summary': 'Liverpool', '_xscrape_media': [],
             '_xscrape_quoted': {'media': [{'type': 'video', 'url': 'https://video.twimg.com/clip.mp4'}]}}
    item = twitter.build_tweet_item(entry, 'report')
    assert item['image'] is None
    assert item['video_url'].endswith('.mp4')


def test_nitter_html_keeps_both_own_and_quote_photos():
    own = 'https://pbs.twimg.com/media/own.jpg'
    quoted = 'https://pbs.twimg.com/media/quoted.jpg'
    entry = {'link': 'https://x.com/report/status/12', 'title': 'Liverpool update',
             'summary': f'<img src="{own}"><blockquote><img src="{quoted}"></blockquote>'}
    item = twitter.build_tweet_item(entry, 'report')
    assert item['images'] == [own, quoted]


@pytest.mark.parametrize('failure', ['missing', 'offline'])
def test_missing_or_offline_preview_is_cached_without_losing_news(monkeypatch, failure):
    calls = []
    def unavailable(url, **kwargs):
        calls.append(url)
        if failure == 'offline':
            raise ConnectionError('offline')
        return '<main><img src="data:image/png;base64,blank"><img src="/logo.svg"></main>'
    monkeypatch.setattr(media_preview, 'http_get', unavailable)
    for _ in range(2):
        item = {'source': 'Twitter', 'title': 'Liverpool update', 'linked_urls': [TIMES_URL]}
        media_preview.enrich(item)
        assert item['image'] is None
        assert item['title'] == 'Liverpool update'
    assert calls == [TIMES_URL]


def test_existing_images_and_disabled_media_do_not_fetch(monkeypatch):
    monkeypatch.setattr(media_preview, 'http_get', lambda *a, **k: pytest.fail('no fetch expected'))
    item = {'source': 'Twitter', 'images': [GAKPO_IMAGE], 'linked_urls': [TIMES_URL]}
    media_preview.enrich(item)
    assert item['image'] == GAKPO_IMAGE
    monkeypatch.setattr(config, 'ENABLE_AUTO_IMAGE', False)
    media_preview.enrich({'source': 'Twitter', 'linked_urls': [TIMES_URL]})
    monkeypatch.setattr(config, 'ENABLE_AUTO_IMAGE', True)
    monkeypatch.setattr(config, 'ENABLE_TWITTER_MEDIA', False)
    media_preview.enrich({'source': 'Twitter', 'linked_urls': [TIMES_URL]})


def test_link_preview_uses_browser_header_only_for_that_request(monkeypatch):
    calls = []
    original_agent = config.USER_AGENT
    def fetch(url, **kwargs):
        calls.append(kwargs)
        return f'<meta property="og:image" content="{GAKPO_IMAGE}">' if kwargs['headers']['User-Agent'] == 'Mozilla/5.0' else '<html>challenge</html>'
    monkeypatch.setattr(media_preview, 'http_get', fetch)
    item = {'source': 'Twitter', 'linked_urls': [TIMES_URL]}
    media_preview.enrich(item)
    assert item['image'] == GAKPO_IMAGE
    assert calls[0]['timeout'] <= 12
    assert config.USER_AGENT == original_agent


def test_unrelated_news_never_fetches_link_preview(patched_main, monkeypatch):
    monkeypatch.setattr(media_preview, 'http_get', lambda *a, **k: pytest.fail('relevance must run first'))
    item = {'source': 'Twitter', 'title': 'Raphinha signs Barcelona contract',
            'url': 'https://x.com/romano/status/12', 'linked_urls': [TIMES_URL]}
    assert not patched_main.process_item(item)


def test_preview_rejects_placeholder_and_handles_relative_picture_sources():
    html = '<article><img srcset="," src="data:image/png;base64,x"><picture><source srcset="/big.jpg 1200w, /small.jpg 400w"><img src="data:image/png;base64,x"></picture></article>'
    assert media_preview.page_image(html, TIMES_URL) == 'https://www.thetimes.com/big.jpg'
    assert media_preview.image_url('https://[bad') is None
    assert media_preview.linked_urls({'summary': 'https://[bad https://x.com/a/status/1'}) == []
