"""منبع جدید: فیدهای RSS رسمی خبرگزاری‌ها (BBC و...).

برخلاف نیتر (که پل غیررسمی برای توییتر است و مدام آفلاین می‌شود)، این
فیدها مستقیماً از خود خبرگزاری می‌آیند و هیچ وابستگی به آینه/میرور ندارند —
تقریباً همیشه بالاهستند. برای افزودن فید جدید کافی است آدرسش را به
`OUTLET_RSS_FEEDS` در .env اضافه کنی — نیازی به تغییر کد نیست.
"""
import email.utils
import logging
import time

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
        log.info("feed %s (%s): %d relevant items", name, feed_url, got)
    return out


# ---------------------------------------------------------------- منابع جدید (اختیاری)
# فهرست فیدهای آماده‌ی «فقط لیورپول». پیش‌فرض همه خاموش‌اند؛ با
# OUTLET_RSS_SOURCES در .env روشن می‌شوند (مثلاً guardian,football365 یا all).
# این مسیر جدا از fetch() بالاست و فید BBC / OUTLET_RSS_FEEDS را تغییر نمی‌دهد.
# همه‌ی این فیدها اختصاصی لیورپول‌اند، پس فیلتر کلمه (RELEVANCE_KEYWORDS) لازم نیست.
CATALOG = {
    "football365": {
        "name": "Football365",
        "url": "https://www.football365.com/liverpool/rss2",
    },
    "liverpoolcom": {
        "name": "Liverpool.com",
        "url": "https://www.liverpool.com/?service=rss",
    },
    "guardian": {
        "name": "The Guardian",
        "url": "https://www.theguardian.com/football/liverpool/rss",
    },
    "thisisanfield": {
        "name": "This Is Anfield",
        "url": "https://www.thisisanfield.com/feed/",
    },
}

_warned_unknown = set()


def enabled_source_ids():
    """شناسه‌های معتبر فعال‌شده در OUTLET_RSS_SOURCES، بدون تکرار و به‌ترتیب."""
    raw = [str(x).strip().lower() for x in getattr(config, "OUTLET_RSS_SOURCES", []) or []]
    if "all" in raw:
        return list(CATALOG)
    out = []
    for sid in raw:
        if not sid or sid in out:
            continue
        if sid not in CATALOG:
            if sid not in _warned_unknown:
                _warned_unknown.add(sid)
                log.warning("OUTLET_RSS_SOURCES: unknown source %r (valid: %s)",
                            sid, ", ".join(CATALOG))
            continue
        out.append(sid)
    return out


def _too_old(published, max_hours):
    """True فقط وقتی تاریخ قابل‌خواندن است و از max_hours قدیمی‌تر.
    تاریخ خالی/نامعتبر = نگه‌دار (هیچ خبری به‌خاطر فرمت تاریخ گم نشود)."""
    if not max_hours or max_hours <= 0 or not published:
        return False
    try:
        dt = email.utils.parsedate_to_datetime(published)
        if dt.tzinfo is None:
            return False
        return (time.time() - dt.timestamp()) > max_hours * 3600
    except Exception:
        return False


def fetch_extra(limit=6):
    """فیدهای فعال‌شده‌ی کاتالوگ. سقف `limit` برای هر منبع جداست، تا یک فید
    شلوغ فیدهای بعدی را گرسنه نگذارد. خبر کهنه‌تر از OUTLET_RSS_MAX_AGE_HOURS
    رد می‌شود تا با روشن‌کردن یک منبع، پیام‌های چند روزه‌ی قدیمی به گروه نریزد."""
    ids = enabled_source_ids()
    if not ids:
        return []

    legacy = {u.strip() for u in getattr(config, "OUTLET_RSS_FEEDS", []) if u.strip()}
    max_age = getattr(config, "OUTLET_RSS_MAX_AGE_HOURS", 12)
    out = []
    for sid in ids:
        src = CATALOG[sid]
        if src["url"] in legacy:
            continue  # همین فید را fetch() قدیمی می‌خواند؛ دوباره نمی‌خوانیم
        try:
            entries = parse_rss(src["url"])
        except Exception as e:
            log.warning("feed %s failed: %s", src["url"], e)
            continue
        got = 0
        for e in entries:
            title = clean_text(e.get("title") or "")
            summary = clean_text(e.get("summary") or "")
            link = e.get("link") or ""
            if not title or not link:
                continue
            if _too_old(e.get("published"), max_age):
                continue
            out.append(
                {
                    "source": src["name"],
                    "source_tag": src["name"],
                    "url": link,
                    "title": title,
                    "body": summary or title,
                    "image": e.get("image"),
                }
            )
            got += 1
            if got >= limit:
                break
        log.info("feed %s (%s): %d items", src["name"], sid, got)
    return out
