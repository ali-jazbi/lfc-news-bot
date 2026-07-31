"""منبع جدید: فیدهای RSS رسمی خبرگزاری‌ها (BBC و...).

برخلاف نیتر (که پل غیررسمی برای توییتر است و مدام آفلاین می‌شود)، این
فیدها مستقیماً از خود خبرگزاری می‌آیند و هیچ وابستگی به آینه/میرور ندارند —
تقریباً همیشه بالاهستند. برای افزودن فید جدید کافی است آدرسش را به
`OUTLET_RSS_FEEDS` در .env اضافه کنی — نیازی به تغییر کد نیست.
"""
import logging

import config
from sources.base import parse_rss, clean_text

log = logging.getLogger("src.outlet_rss")

# فقط برای نمایش زیبای‌تر در پست — رفتار فیلترینگ را عوض نمی‌کند
_OUTLET_NAMES = (
    ("bbci.co.uk", "BBC Sport"),
    ("bbc.co.uk", "BBC Sport"),
    ("skysports.com", "Sky Sports"),
    ("theguardian.com", "The Guardian"),
    ("espn.com", "ESPN"),
    ("theathletic.com", "The Athletic"),
    ("mirror.co.uk", "The Mirror"),
    ("liverpoolecho.co.uk", "Liverpool Echo"),
)

# اگر فید مختص یک تیم نباشد (مثلاً فید کلی ورزشی)، فقط خبرهایی که این
# کلمات را دارند قبول می‌شوند (مشابه فیلتر ROMANO_KEYWORDS ولی مستقل)
RELEVANCE_KEYWORDS = (
    "liverpool", "lfc", "anfield", "merseyside", "salah", "slot", "van dijk",
    "virgil", "szoboszlai", "mac allister", "gakpo", "gravenberch",
)


def _outlet_name(url):
    low = url.lower()
    for needle, name in _OUTLET_NAMES:
        if needle in low:
            return name
    return "خبرگزاری"


def _team_specific(url):
    """فیدهای اختصاصی تیم (مثلاً .../teams/liverpool/...) نیازی به فیلتر کلمه ندارند."""
    low = url.lower()
    return "liverpool" in low or "/lfc" in low


def _is_relevant(url, title, summary):
    if _team_specific(url):
        return True
    text = (title + " " + summary).lower()
    return any(kw in text for kw in RELEVANCE_KEYWORDS)


def fetch(limit=6):
    feeds = [f.strip() for f in getattr(config, "OUTLET_RSS_FEEDS", []) if f.strip()]
    if not feeds:
        return []

    out = []
    for feed_url in feeds:
        try:
            entries = parse_rss(feed_url)
        except Exception as e:
            log.warning("feed %s failed: %s", feed_url, e)
            continue
        name = _outlet_name(feed_url)
        got = 0
        for e in entries:
            title = clean_text(e.get("title") or "")
            summary = clean_text(e.get("summary") or "")
            link = e.get("link") or ""
            if not title or not link:
                continue
            if not _is_relevant(feed_url, title, summary):
                continue
            out.append(
                {
                    "source": name,
                    "source_tag": name,
                    "url": link,
                    "title": title,
                    "body": summary or title,
                    "image": e.get("image"),
                }
            )
            got += 1
            if len(out) >= limit:
                return out
        log.info("فید %s (%s): %d خبر مرتبط", name, feed_url, got)
    return out
