"""ابزارهای مشترک منابع: HTTP، پارس HTML، پارس RSS."""
import html as html_mod
import logging
import re

import requests

import config

log = logging.getLogger("src.base")

_session = requests.Session()
_session.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "en-GB,en"})
if config.PROXY:
    _session.proxies = {"http": config.PROXY, "https": config.PROXY}


def http_get(url, timeout=25):
    try:
        r = _session.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.text
        log.warning("GET %s -> %s", url, r.status_code)
    except Exception as e:
        log.warning("GET %s failed: %s", url, e)
    return None


def soup_of(html):
    from bs4 import BeautifulSoup
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def meta(soup, prop):
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def clean_text(text):
    if not text:
        return ""
    text = html_mod.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def first_image_in_html(fragment):
    if not fragment:
        return None
    m = re.search(r'<img[^>]+src="([^"]+)"', fragment)
    return m.group(1) if m else None


def images_in_html(fragment, max_imgs=10):
    """همه <img> های یک تکه HTML — بدون تکرار و با سقف."""
    out, seen = [], set()
    for m in re.finditer(r'<img[^>]+src="([^"]+)"', fragment or ""):
        u = html_mod.unescape(m.group(1))
        if u and u not in seen:
            seen.add(u)
            out.append(u)
            if len(out) >= max_imgs:
                break
    return out


def extract_tweet_id_from_link(link):
    """آیدی عددی توییت از لینک نیتر (/status/<id>#m)."""
    m = re.search(r"/status(?:es)?/(\d+)", link or "")
    return m.group(1) if m else None


def parse_rss(url, timeout=25, raw=None):
    """خروجی: لیستی از dict با کلیدهای title, link, summary, image.

    اگر raw داده شود، همان متن استفاده می‌شود و دوباره گرفته نمی‌شود
    (برای وقتی خودمان خام را گرفتیم تا وضعیت 429 را هم تشخیص دهیم).
    """
    import feedparser
    try:
        if raw is None:
            raw = http_get(url, timeout=timeout)
        feed = feedparser.parse(raw if raw else url)
    except Exception as e:
        log.warning("rss %s failed: %s", url, e)
        return []

    out = []
    for e in getattr(feed, "entries", []):
        summary = e.get("summary", "") or e.get("description", "")
        image = None
        for m in e.get("media_content", []) or []:
            if m.get("url"):
                image = m["url"]
                break
        if not image:
            for l in e.get("links", []) or []:
                if str(l.get("type", "")).startswith("image"):
                    image = l.get("href")
                    break
        if not image:
            image = first_image_in_html(summary)
        out.append(
            {
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "summary": summary,
                "image": image,
                "published": e.get("published", ""),
            }
        )
    return out
