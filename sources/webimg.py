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
# نتیجهٔ جستجو تا این مدت (ثانیه) کش می‌ماند تا هر سیکل دوباره جستجو نشود؛
# بعد از آن دوباره ارزیابی می‌شود تا یک عکسِ اشتباه برای همیشه نچسبد.
_CACHE_TTL = 7 * 24 * 3600

# نام‌های ثابت باشگاه که حتی بدون نام بازیکن، جستجوی عکس را به نتیجهٔ خوب می‌رسانند.
_CLUB_ENTITIES = (
    "liverpool", "anfield", "kirkby", "merseyside derby", "kop",
    "lfc women", "liverpool women",
)

# برخی نام‌های ثابت در جستجوی کامنز مبهم‌اند (مثلاً «liverpool women» مرکز بهداشت
# هم می‌آورد) — نسخهٔ دقیق‌تر هم امتحان می‌شود.
_CLUB_ENTITY_VARIANTS = {
    "liverpool women": ("liverpool fc women",),
}

# نام رقابت‌ها که عکسِ جدا ندارند — جستجوی «Premier League» عکسِ باشگاه برمی‌گرداند.
# وقتی فقط همین‌ها در عنوان باشند، عکس نمی‌گذاریم.
_COMPETITIONS = (
    "premier league", "champions league", "carabao cup", "fa cup",
    "europa league", "world cup", "super cup",
)

# فایل‌هایی که در کامنز محبوب ولی برای خبر بی‌ربط‌اند.
_BAD_FILES = re.compile(
    r"(montage|collage|composite|seawise|logo|badge|crest|emblem|icon|sprite|"
    r"blank|placeholder|spacer|pixel|1x1|transparent|loading|stub|"
    r"health\s*centre|health\s*center)",
    re.IGNORECASE,
)

# برای تطبیقِ نیمه‌کلمه‌ای: «Confirmed Liverpool line» هم «line» را می‌گیرد
# (بین confirmed و line کلمات دیگر هم بیاید). این نشانه‌ها یعنی خبر خبرنگاریِ
# عام (پیش‌نمایش، آلبوم، دورهمی) است که عکسِ جدا معنی ندارد.
_NO_IMG_RE = re.compile(
    r"\b(watch\s+highlights?|reaction|preview|roundup|recap|"
    r"confirmed\s+\w*\s*line|team\s+news|prediction|odds|line-?up|"
    r"highlights?|sightseeing|tour|diary|gallery|quiz)\b",
    re.IGNORECASE,
)


def _glossary_entities():
    """نام‌های شناخته‌شده از glossary.json (بازیکن، مربی، تیم حریف، ورزشگاه).

    فقط کلیدهای «اسم خاص» (با بیش از یک کلمه) به کار می‌روند. عبارت‌های ترجمه‌ای
    مثل «contract extension»، «personal terms» و... عکسِ جدا ندارند و نویزند.
    نام‌های با ذرات «van/der/de» هم قبول است (Virgil van Dijk).
    """
    out = []
    try:
        for k in config.GLOSSARY:
            k = k.strip()
            words = k.split()
            if len(words) < 2:
                continue
            # ذرات نام (van/der/de) می‌توانند کوچک باشند
            def _name_word(w):
                return bool(re.match(r"^[A-Z][a-z]+$", w)) or w.lower() in ("van", "der", "de", "den")
            if all(_name_word(w) for w in words):
                out.append(k)
    except Exception:
        pass
    return out


# کلیدهای glossارy که بیش از یک کلمه دارند — در زمان import ساخته می‌شود تا هر بار
# از نو ساخته نشود. از تعریف به‌جای اجرای تابع برای راحتی خواندن استفاده می‌کنیم.
_GLOSS_ENTITIES = None


def _glossary_matches(title):
    """هر کدام از نام‌های شناخته‌شده که در عنوان هست، برمی‌گرداند (به‌ترتیب طول).

    نام رقابت‌ها (لیگ برتر و...) را برنمی‌گرداند چون عکسِ جدا ندارند.
    """
    global _GLOSS_ENTITIES
    if _GLOSS_ENTITIES is None:
        _GLOSS_ENTITIES = [g for g in _glossary_entities() if g.lower() not in _COMPETITIONS]
    low = (title or "").lower()
    found = [g for g in _GLOSS_ENTITIES if g.lower() in low]
    found.sort(key=len, reverse=True)
    return found


def _person_names(title, body="", max_n=3):
    """عبارات اسم‌مانندِ حروف بزرگ از عنوان (احتمالاً نام بازیکن/مربی/مسئول).

    فقط عبارت‌های چندکلمه‌ای (First Last) قبول می‌شوند تا «liverpool»، «Leeds»
    و تک‌کلمه‌های عام به‌عنوان اسم در نیایند. نام باید در متن خبر هم آمده باشد
    تا اسم واقعی تأیید شود (برای جلوگیری از «Mr Beef»).
    """
    blob = " " + (title or "") + " " + (body or "") + " "
    names = []
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", title or ""):
        cand = m.group(1)
        low = cand.lower()
        if any(w in low for w in ("fc", "the", "tv", "ltd", "united", "city")) \
                or len(cand) < 5:
            continue
        if low in names:
            continue
        # نام باید در متن خبر هم آمده باشد تا اسم واقعی تأیید شود
        if low not in blob.lower():
            continue
        names.append(low)
        if len(names) >= max_n:
            break
    return names


def _keywords(title, body=""):
    """چند عبارت جستجو برای عکس: اول نام‌های شناخته‌شده، بعد اسم‌های عنوان.

    خروجی لیستِ عبارات جستجو به‌ترتیب اولویت است (هر کدام یک query کامنز).
    """
    queries = []
    low_t = (title or "").lower()

    # ۱. اسم‌های احتمالی بازیکن/مربی در عنوان — اولویت اول چون دقیق‌ترین عکس را می‌دهد
    for name in _person_names(title, body):
        queries.append(name)

    # ۲. نام‌های شناخته‌شده از glossary که در عنوان آمده‌اند
    for ent in _glossary_matches(title):
        queries.append(ent)

    # ۳. نام‌های ثابت باشگاه — فقط وقتی خبر واقعاً دربارهٔ خود باشگاه/ورزشگاه است
    if not queries and not any(c in low_t for c in _COMPETITIONS):
        for ent in _CLUB_ENTITIES:
            if ent in low_t:
                queries.append(ent)
                break

    # dedupe با حفظ ترتیب
    seen = set()
    out = []
    for q in queries:
        q = q.strip()
        if not q:
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out[:4]


def _load_cache():
    """کش را می‌خواند؛ ورودی‌های کهنه (قدیمی‌تر از TTL) را پاک می‌کند."""
    try:
        with io.open(_CACHE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    now = time.time()
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict) and v.get("t") and now - v.get("t", 0) > _CACHE_TTL:
            continue  # کهنه — دوباره ارزیابی می‌شود
        out[k] = v
    return out


def _save_cache(cache):
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with io.open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        log.debug("webimg cache save failed: %s", e)


def _cache_get(cache, key):
    """مقدار کش را برمی‌گرداند؛ هم فرمت جدید {u,t} و هم فرمت قدیم url-string را می‌فهمد."""
    v = cache.get(key)
    if isinstance(v, dict):
        return v.get("u")
    return v


def _cache_set(cache, key, value):
    cache[key] = {"u": value, "t": time.time()}


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


def _file_info(title, timeout=8):
    """ابعاد و URL عکس کامنز را برمی‌گرداند.

    خروجی (width, height, url) یا None. از تصویرِ کوچک (آیکون/لوگو/بنر) صرف‌نظر
    می‌شود چون در کانال زشت دیده می‌شود.
    """
    headers = {"User-Agent": _UA}
    params = {
        "action": "query", "format": "json", "titles": title,
        "prop": "imageinfo", "iiprop": "url|size", "iiurlwidth": "1200",
    }
    try:
        r = requests.get(_API, params=params, headers=headers, timeout=timeout)
        pages = r.json().get("query", {}).get("pages", {})
        for pg in pages.values():
            ii = (pg.get("imageinfo") or [{}])[0]
            w = ii.get("width") or 0
            h = ii.get("height") or 0
            # عکس‌های خیلی کوچک (آیکون/لوگو) برای پست مناسب نیستند
            if w and h and (w < 300 or h < 300):
                continue
            u = ii.get("thumburl") or ii.get("url")
            if u:
                return w, h, u
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
        return _cache_get(cache, ck) or None

    # برای خبرهای عام (مصاحبه، نقل‌وانتقال، خبر فنی) عکس جدا نمی‌گذاریم — بهتر
    # از یک عکس بی‌ربط. فقط وقتی ادامه می‌دهیم که یک نام شناخته‌شده یا اسمِ
    # بازیکن/مربی در عنوان باشد.
    low_t = (title or "").lower()
    queries = _keywords(title, body)
    if not queries:
        _cache_set(cache, ck, None)
        _save_cache(cache)
        return None

    # خبرهای خبرنگاریِ عام (آلبوم، دورهمی، پیش‌نمایش) بدون نام شناخته‌شده —
    # عکسِ جدا نمی‌گذاریم تا یک عکس بی‌ربط (مثلاً عکس گوشت یا قبر) نیاید.
    if _NO_IMG_RE.search(low_t) and not _glossary_matches(title):
        _cache_set(cache, ck, None)
        _save_cache(cache)
        return None

    # جستجو روی هر عبارت به‌ترتیب — به‌جای اضافه کردن «Liverpool FC» که نتیجه را
    # به سمت باشگاه می‌کشاند، همان عبارت را مستقیم جستجو می‌کنیم.
    search_queries = list(queries)
    for q in queries:
        ql = q.lower()
        if ql in _CLUB_ENTITY_VARIANTS:
            search_queries.extend(_CLUB_ENTITY_VARIANTS[ql])
    for q in search_queries:
        # هر عبارت را دوبار جستجو می‌کنیم چون ترتیب نتایج کامنز کمی جابه‌جا می‌شود
        # و ممکن است بار اول تصویرِ درست پایین‌تر از حدِ برش بیفتد.
        titles = []
        for _ in range(2):
            titles = _commons_search(q, limit=8, timeout=timeout)
            if titles:
                break
        # فقط فایل‌های jpg/png/webp (نه svg/gif/بوم) و نه لوگو/مونتاژ بی‌ربط
        titles = [
            t for t in titles
            if re.search(r"\.(jpe?g|png|webp)\b", t, re.I) and not _BAD_FILES.search(t)
        ]
        # فایل‌هایی که نامِ جستجو را در اسم‌شان دارند، مرتبط‌ترند — اول امتحان
        # می‌شوند تا عکسِ یک تیم/بازیکنِ دیگر به اشتباه نیاید.
        q_words = [w.lower() for w in re.findall(r"[A-Za-z]+", q) if len(w) > 2]
        titles.sort(
            key=lambda t: sum(1 for w in q_words if w in t.lower()),
            reverse=True,
        )
        for t in titles:
            info = _file_info(t, timeout=timeout)
            if not info:
                continue
            _, _, u = info
            _cache_set(cache, ck, u)
            _save_cache(cache)
            log.info("auto-image for '%s' -> %s", (title or "")[:40], u[:70])
            return u

    _cache_set(cache, ck, None)
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
