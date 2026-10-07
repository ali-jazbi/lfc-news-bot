"""Original news images, including lazy images and linked article previews."""
import html
import logging
import re
import time
from urllib.parse import urljoin, urlsplit

import config
from sources.base import http_get, meta, soup_of

log = logging.getLogger('src.media_preview')
_cache = {}
_SKIP = re.compile(r'logo|icon|avatar|sprite|placeholder|badge|crest|blank|spacer|pixel|transparent|1x1', re.I)
_TWEET_HOSTS = {'x.com', 'twitter.com', 'mobile.twitter.com', 'www.twitter.com', 'www.x.com'}


def image_url(value, base_url=''):
    if not isinstance(value, str) or not value.strip() or value.startswith('data:'):
        return None
    url = urljoin(base_url, html.unescape(value.strip()))
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme not in ('https', 'http') or not parsed.hostname:
        return None
    if _SKIP.search(parsed.path.rsplit('/', 1)[-1]) or parsed.path.lower().endswith('.svg'):
        return None
    return url


def element_image(node, base_url):
    """Prefer full lazy/srcset images; never return data placeholders."""
    if node is None:
        return None
    elements = [node] if node.name in ('img', 'source') else node.find_all(['img', 'source'])
    for element in elements:
        for attr in ('data-srcset', 'srcset', 'data-src', 'data-original', 'src'):
            value = element.get(attr)
            if not value:
                continue
            candidates = value.split(',') if attr.endswith('srcset') else [value]
            if attr.endswith('srcset'):
                def size(candidate):
                    match = re.search(r'\s(\d+(?:\.\d+)?)[wx]\s*$', candidate)
                    return float(match.group(1)) if match else 0
                candidates.sort(key=size, reverse=True)
            for candidate in candidates:
                parts = candidate.strip().split()
                url = image_url(parts[0], base_url) if parts else None
                if url:
                    return url
    return None


def page_image(document, url):
    soup = soup_of(document)
    for prop in ('og:image:secure_url', 'og:image', 'twitter:image', 'twitter:image:src', 'article:image'):
        image = image_url(meta(soup, prop), url)
        if image:
            return image
    article = soup.find('article') or soup.find('main')
    return element_image(article, url)


def linked_urls(entry):
    """Keep expanded source URLs before tweet_text removes them."""
    texts = [entry.get('summary') or entry.get('body') or '', entry.get('title') or '']
    quote = entry.get('_xscrape_quoted') or {}
    texts.append(quote.get('text') or '')
    out = []
    for text in texts:
        candidates = re.findall(r'href=["\x27]([^"\x27]+)["\x27]', text, re.I)
        plain = html.unescape(re.sub(r'<[^>]+>', ' ', text))
        candidates += re.findall(r'https?://[^\s<>"\x27]+', plain)
        for value in candidates:
            value = html.unescape(value).rstrip('.,);]')
            try:
                parsed = urlsplit(value)
            except ValueError:
                continue
            if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.hostname in _TWEET_HOSTS:
                continue
            if value not in out:
                out.append(value)
    return out


def enrich(item):
    """Fetch missing previews only for news already selected for processing."""
    if not config.ENABLE_AUTO_IMAGE:
        return
    is_tweet = item.get('source') == 'Twitter'
    if is_tweet and not config.ENABLE_TWITTER_MEDIA:
        return
    images = [u for value in item.get('images') or [] if (u := image_url(value))]
    image = image_url(item.get('image'))
    if image or images:
        item['image'] = image or images[0]
        item['images'] = images or [item['image']]
        return
    item['image'], item['images'] = None, []
    if item.get('video_url'):
        return
    urls = (item.get('linked_urls') or linked_urls(item.get('raw_entry') or item)) if is_tweet else [item.get('url')]
    for url in urls[:3]:
        try:
            parsed = urlsplit(url or '')
        except ValueError:
            continue
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.hostname in _TWEET_HOSTS:
            continue
        now = time.time()
        hit = _cache.get(url)
        if hit and now - hit[0] < config.TWITTER_ENRICH_TTL:
            image = hit[1]
        else:
            try:
                document = http_get(url, timeout=min(config.REQUEST_TIMEOUT, 12),
                                    headers={'User-Agent': 'Mozilla/5.0'})
                image = page_image(document, url) if document else None
            except Exception as exc:
                log.debug('article preview unavailable for %s: %s', url, exc)
                image = None
            if len(_cache) >= 1024:
                _cache.pop(next(iter(_cache)))
            _cache[url] = (now, image)
        if image:
            item.update(image=image, images=[image], image_source_url=url)
            return
