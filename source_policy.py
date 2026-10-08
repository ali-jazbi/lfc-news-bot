"""One source switch for polling, stored queues and delivery of old drafts."""
import re
from urllib.parse import urlsplit

import config


def source_enabled(source_id):
    if config.CORE_SOURCES_ONLY and source_id not in ('twitter', 'lfc_official'):
        return False
    flags = {
        'twitter': config.ENABLE_TWITTER,
        'lfc_official': config.ENABLE_LFC,
        'outlet_rss': config.ENABLE_OUTLET_RSS,
        'rss_extra': config.ENABLE_OUTLET_RSS and bool(config.OUTLET_RSS_SOURCES),
        'news_search': config.ENABLE_NEWS_SEARCH,
        'bluesky': config.ENABLE_BLUESKY,
        'romano': config.ENABLE_ROMANO,
    }
    return flags.get(source_id, False)


def core_url(url):
    try:
        parsed = urlsplit(url or '')
    except ValueError:
        return None
    if parsed.scheme not in ('http', 'https'):
        return None
    if parsed.hostname in ('liverpoolfc.com', 'www.liverpoolfc.com'):
        if re.fullmatch(r'/(?:news|article)/(?!listing/?$|category/?$)[^/]+/?', parsed.path):
            return 'lfc_official'
    if parsed.hostname in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com'):
        if re.fullmatch(r'/(?:[\w]+|i/web)/status/\d+/?', parsed.path):
            return 'twitter'
    return None


def disabled_reason(item):
    source_id = item.get('source_id')
    if not source_id or source_id == 'collected':
        source_id = {'Twitter': 'twitter', 'LFC Official': 'lfc_official',
                     'LFC Google fallback': 'lfc_official', 'News search': 'news_search',
                     'Bluesky': 'bluesky'}.get(item.get('source'))
    known = {'twitter', 'lfc_official', 'outlet_rss', 'rss_extra', 'news_search', 'bluesky', 'romano'}
    if source_id in known and not source_enabled(source_id):
        return 'source disabled: ' + source_id
    if config.CORE_SOURCES_ONLY:
        origin = core_url(item.get('url'))
        if not origin or not source_enabled(origin):
            return 'source disabled: only Twitter statuses and direct LFC news are enabled'
        # Old story grouping may have replaced a tweet's body with RSS text.
        if item.get('text_source_url') and not core_url(item['text_source_url']):
            return 'source disabled: text was imported from a non-core source'
    elif source_id == 'lfc_official':
        if not core_url(item.get('url')) and not config.ENABLE_LFC_GOOGLE_FALLBACK:
            return 'source disabled: official Google News fallback'
    return None
