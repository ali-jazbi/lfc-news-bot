"""منبع ۲: توییتر فابریتسیو رومانو.

چون API رسمی X برای خواندن رایگان نیست، از فیدهای RSS پل (RSSHub / Nitter)
استفاده می‌کنیم. لیست فیدها در .env قابل تغییر است و اولین فیدی که
جواب بدهد انتخاب می‌شود (fail-over خودکار).
"""
import logging
import re

import config
from sources.base import parse_rss, clean_text

log = logging.getLogger("src.romano")

# پلان آخر: خبرهایی که از روی توییت‌های رومانو نوشته شده‌اند
GOOGLE_FALLBACK = (
    "https://news.google.com/rss/search?"
    "q=%22Fabrizio+Romano%22+Liverpool+when:2d&hl=en-GB&gl=GB&ceid=GB:en"
)


def _is_relevant(text):
    if not config.ROMANO_KEYWORDS:
        return True
    low = text.lower()
    return any(k.lower() in low for k in config.ROMANO_KEYWORDS)


def _canonical(link):
    """لینک nitter/rsshub را به لینک اصلی x.com تبدیل می‌کند (برای dedup درست)."""
    m = re.search(r"/status(?:es)?/(\d+)", link or "")
    if m:
        return "https://x.com/FabrizioRomano/status/" + m.group(1)
    return link


def fetch(limit=6):
    entries = []
    for feed_url in config.ROMANO_FEEDS:
        try:
            entries = parse_rss(feed_url)
        except Exception as e:
            log.warning("feed %s failed: %s", feed_url, e)
            continue
        if entries:
            log.info("active romano feed: %s (%d items)", feed_url, len(entries))
            break

    from_google = False
    if not entries and getattr(config, "ROMANO_GOOGLE_FALLBACK", True):
        log.warning("no twitter bridge worked - falling back to Google News")
        try:
            entries = parse_rss(GOOGLE_FALLBACK)
            from_google = bool(entries)
        except Exception as e:
            log.warning("google fallback failed: %s", e)

    if not entries:
        log.error("no romano feed worked — check ROMANO_FEEDS")
        return []

    out = []
    for e in entries:
        text = clean_text(e.get("summary") or e.get("title"))
        if not text or text.startswith("RT "):
            continue
        if not _is_relevant(text):
            continue
        out.append(
            {
                "source": "Fabrizio Romano",
                "source_tag": "Fabrizio Romano" if not from_google else "نقل از رومانو",
                "url": _canonical(e.get("link")),
                "title": text[:200],
                "body": text,
                "image": e.get("image"),
                "priority": True,
            }
        )
        if len(out) >= limit:
            break
    return out
