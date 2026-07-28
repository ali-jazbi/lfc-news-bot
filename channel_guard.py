"""نگهبان کانال — جلوی دوباره‌کاری را می‌گیرد.

پست‌های اخیر خود کانال را از نسخه وب عمومی تلگرام (t.me/s/…) می‌خواند
و ترجمه‌ی تازه را با آن‌ها مقایسه می‌کند. اگر همان خبر قبلاً (حتی دستی
توسط یک ادمین دیگر) منتشر شده باشد، دیگر به گروه نمی‌رود.

مزیت: ربات لازم نیست عضو یا ادمین کانال باشد — فقط کافی است کانال عمومی باشد.
"""
import logging
import re
import time

import config
from sources.base import http_get, soup_of, clean_text

log = logging.getLogger("guard")

_cache = {"at": 0, "posts": [], "ok": False}
_warned = False

# یکسان‌سازی نویسه‌های عربی/فارسی و ارقام
_TRANS = {
    "\u064a": "\u06cc", "\u0649": "\u06cc", "\u0643": "\u06a9",
    "\u0623": "\u0627", "\u0625": "\u0627", "\u0622": "\u0627", "\u0629": "\u0647",
    "\u200c": " ", "\u200f": " ", "\u200e": " ",
}
for _i, _d in enumerate("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"):
    _TRANS[_d] = str(_i)
for _i, _d in enumerate("\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"):
    _TRANS[_d] = str(_i)

_PUNCT = re.compile(r"[^\w\u0600-\u06ff ]+", re.UNICODE)
_SPACES = re.compile(r"\s+")


# اگر config قدیمی بود، به جای کرش مقدار پیش‌فرض برمی‌داریم
_DEFAULTS = {
    "CHANNEL_GUARD": True,
    "CHANNEL_GUARD_THRESHOLD": 82,
    "CHANNEL_GUARD_TTL": 600,
}


def cfg(name):
    return getattr(config, name, _DEFAULTS.get(name))


def norm(text):
    """متن را برای مقایسه ساده می‌کند: بی‌ایموجی، بی‌علامت، یکدست."""
    t = clean_text(text or "")
    for a, b in _TRANS.items():
        t = t.replace(a, b)
    t = _PUNCT.sub(" ", t)
    return _SPACES.sub(" ", t).strip().lower()


def _channel_web_url():
    name = (config.CHANNEL_USERNAME or "").strip().lstrip("@")
    if not name:
        return None
    return "https://t.me/s/" + name


def _scrape(url):
    html = http_get(url, timeout=25)
    if not html:
        return []
    s = soup_of(html)
    out = []
    for div in s.find_all("div", class_="tgme_widget_message_text"):
        txt = clean_text(div.get_text(" ", strip=True))
        if len(txt) > 20:
            out.append(txt)
    return out


def refresh(force=False):
    """پست‌های اخیر کانال را می‌گیرد (با کش تا CHANNEL_GUARD_TTL ثانیه)."""
    global _warned
    now = time.time()
    if not force and _cache["posts"] and now - _cache["at"] < cfg("CHANNEL_GUARD_TTL"):
        return _cache["posts"]

    url = _channel_web_url()
    if not url:
        return []

    try:
        posts = _scrape(url)
    except Exception as e:
        log.warning("خواندن کانال نشد: %s", e)
        posts = []

    if posts:
        _cache.update({"at": now, "posts": posts, "ok": True})
        _warned = False
        log.info("نگهبان کانال: %d پست اخیر خوانده شد", len(posts))
    else:
        _cache["at"] = now
        _cache["ok"] = False
        if not _warned:
            log.warning(
                "پست‌های کانال %s خوانده نشد — فیلتر کانال موقتاً غیرفعال است",
                config.CHANNEL_USERNAME,
            )
            _warned = True
    return _cache["posts"]


def _score(a, b):
    try:
        from rapidfuzz import fuzz
        return max(fuzz.token_set_ratio(a, b), fuzz.partial_ratio(a, b))
    except ImportError:
        # پلان ب: کتابخانه استاندارد پایتون (کمی دقیق‌تر نیست ولی کار را راه می‌اندازد)
        import difflib
        sa, sb = set(a.split()), set(b.split())
        overlap = 100 * len(sa & sb) / max(1, len(sa))
        return max(overlap, 100 * difflib.SequenceMatcher(None, a, b).ratio())


def check(tr, item=None):
    """اگر این خبر قبلاً در کانال رفته باشد (امتیاز، نمونه پست) وگرنه None."""
    if not cfg("CHANNEL_GUARD"):
        return None

    posts = refresh()
    if not posts:
        return None

    title = norm((tr or {}).get("title"))
    body = norm((tr or {}).get("body"))
    if len(title) < 12:
        return None

    probe = title if len(title) >= 25 else (title + " " + body[:120]).strip()
    best, best_post = 0, ""

    for post in posts:
        p = norm(post)
        if not p:
            continue
        sc = _score(probe, p)
        if sc > best:
            best, best_post = sc, post

    if best >= cfg("CHANNEL_GUARD_THRESHOLD"):
        return best, best_post[:110]
    return None


def status():
    """خلاصه وضعیت برای دستور /health"""
    if not cfg("CHANNEL_GUARD"):
        return "\u26aa نگهبان کانال: غیرفعال"
    posts = refresh()
    if posts:
        return (
            "\u2705 نگهبان کانال: " + str(len(posts)) + " پست اخیر از "
            + str(config.CHANNEL_USERNAME)
            + " \u00b7 آستانه " + str(cfg("CHANNEL_GUARD_THRESHOLD")) + "%"
        )
    return "\u274c نگهبان کانال: پستی خوانده نشد (کانال خصوصی یا شبکه)"
