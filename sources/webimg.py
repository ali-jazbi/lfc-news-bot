"""پیدا کردن یک عکس مرتبط برای خبرهایی که عکس ندارند — از ویکی‌مدیا کامانز.

رایگان و بدون کلید است (فقط User-Agent مناسب لازم است). جستجو بر اساس
کلمات کلیدی عنوان خبر انجام می‌شود و یک تصویر واقعی برمی‌گرداند.

قواعد:
  • فقط وقتی استفاده می‌شود که خود خبر عکس نداشته باشد.
  • برای آپدیت‌های لحظه‌ایِ مسابقه (تعویض/گلِ در جریان) عکس ساخته نمی‌شود.
  • نتیجه در یک کش فایل ذخیره می‌شود تا هر سیکل دوباره جستجو نکنیم.
"""
import io
import json
import logging
import os
import re
import time

import requests

import config

log = logging.getLogger("src.webimg")

_API = "https://commons.wikimedia.org/w/api.php"
_UA = "LFCNewsBot/1.0 (Telegram football news bot)"
_CACHE_PATH = os.path.join("data", "webimg_cache.json")

# کلمات بی‌ارزش که برای جستجوی عکس به کار نمی‌آیند
_STOP = re.compile(
    r"\b(the|a|an|and|or|of|to|in|on|at|for|with|from|by|is|are|was|were|"
    r"has|have|had|his|her|their|our|your|it|its|this|that|as|be|been|"
    r"will|can|could|would|should|about|after|before|over|under|out|up|"
    r"into|not|no|so|but|more|most|all|every|new|latest|watch|full|read|"
    r"match|report|news|live|update|pre|season|tour)\b",
    re.IGNORECASE,
)


def _load_cache():
    try:
        with io.open(_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with io.open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        log.debug("webimg cache save failed: %s", e)


def _keywords(title, body=""):
    """چند کلمه کلیدی مفید از عنوان برای جستجوی عکس."""
    words = []
    for w in re.split(r"[^A-Za-z0-9]+", (title or "") + " " + (body or "")):
        w = w.strip()
        if len(w) >= 3 and not _STOP.search(w) and w.lower() not in words:
            words.append(w.lower())
        if len(words) >= 4:
            break
    return words


def _commons_search(query, limit=3, timeout=8):
    headers = {"User-Agent": _UA}
    params = {
        "action": "query", "list": "search", "format": "json",
        "srsearch": query, "srnamespace": "6", "srlimit": str(limit),
    }
    try:
        r = requests.get(_API, params=params, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return []
        return [it.get("title") for it in r.json().get("query", {}).get("search", [])]
    except Exception as e:
        log.debug("webimg search failed: %s", e)
        return []


def _file_url(title, timeout=8):
    headers = {"User-Agent": _UA}
    params = {
        "action": "query", "format": "json", "titles": title,
        "prop": "imageinfo", "iiprop": "url", "iiurlwidth": "1200",
    }
    try:
        r = requests.get(_API, params=params, headers=headers, timeout=timeout)
        pages = r.json().get("query", {}).get("pages", {})
        for pg in pages.values():
            ii = (pg.get("imageinfo") or [{}])[0]
            u = ii.get("thumburl") or ii.get("url")
            if u:
                return u
    except Exception as e:
        log.debug("webimg file url failed: %s", e)
    return None


def find_for_article(title, body="", url="", timeout=8):
    """یک عکس مرتبط پیدا می‌کند — خروجی URL تصویر یا None.

    کش به کلید URL خبر تا جستجوی تکراری هر سیکل نشود.
    """
    if not getattr(config, "ENABLE_AUTO_IMAGE", False):
        return None

    cache = _load_cache()
    ck = url or (title or "")[:80]
    if ck in cache:
        return cache[ck] or None

    kws = _keywords(title, body)
    if not kws:
        return None

    # جستجو: کلمات کلیدی + لیورپول برای همیشه مرتبط ماندن
    for base_query in (" ".join(kws), " ".join(kws[:2])):
        titles = _commons_search(base_query + " Liverpool FC", limit=3, timeout=timeout)
        # فقط فایل‌های jpg/png (نه svg/gif)
        titles = [t for t in titles if re.search(r"\.(jpe?g|png|webp)\b", t, re.I)]
        if not titles:
            titles = _commons_search(base_query, limit=3, timeout=timeout)
            titles = [t for t in titles if re.search(r"\.(jpe?g|png|webp)\b", t, re.I)]
        for t in titles:
            u = _file_url(t, timeout=timeout)
            if u:
                cache[ck] = u
                _save_cache(cache)
                log.info("auto-image for '%s' -> %s", (title or "")[:40], u[:70])
                return u

    cache[ck] = None
    _save_cache(cache)
    return None


def is_live_update(item):
    """آیا این خبر یک آپدیت لحظه‌ایِ مسابقه است که عکس مصنوعی نباید بخورد؟"""
    blob = ("%s %s" % (item.get("title") or "", item.get("body") or "")).lower()
    markers = (
        "in the %dth minute", "دقیقه", "substitution", "sub ", " changed",
        "score remains", "score is ", "goal for", "goal!", "goals scored",
        "liverpool score", "went ahead", "equaliser", "equalizer", "red card",
    )
    # تشخیص دقیقه‌های بازی مثل 'in the 68th minute'
    if re.search(r"\bin the \d+(st|nd|rd|th) minute\b", blob):
        return True
    return any(m in blob for m in markers)
