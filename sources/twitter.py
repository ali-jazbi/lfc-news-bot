"""منبع توییتر — چند لایه، برای پایداری واقعی.

چالش اصلی این فایل: گرفتن توییت‌های تازه از آیدی‌های مشخص، به‌صورت پایدار،
بدون پول دادن به API رسمی توییتر. سه لایه به ترتیب امتحان می‌شوند:

۱) سندیکیشن مستقیم توییتر (cdn.syndication.twimg.com) — همان چیزی که خودِ
   توییتر برای نمایش توییت در ویجت/امبد سایت‌های دیگر استفاده می‌کند.
   رایگان و بدون کلید است و به هیچ آینه‌ای وابسته نیست، پس وقتی جواب می‌دهد
   از همه پایدارتر است. نقطه ضعفش: مستند رسمی ندارد، ساختار پاسخش می‌تواند
   بدون اطلاع عوض شود و گاهی نرخش محدود می‌شود. برای همین با احتیاط پارس
   می‌شود (به‌جای وابستگی به یک مسیر ثابت در JSON، کل درخت پاسخ گشته می‌شود)
   و اگر هر جای این لایه شکست بخورد، بقیه خط لوله دست‌نخورده می‌ماند.

۲) آینه‌های نیتر (RSS) — همان روال قبلی، ولی حالا با «امتیاز سلامت»:
   هر آینه که در سنجش دوره‌ای شکست بخورد یک backoff نمایی می‌گیرد (۵ دقیقه،
   ۱۰، ۲۰، ... تا سقف ۶ ساعت) و تا آن زمان دیگر امتحان نمی‌شود، مگر این‌که
   همه آینه‌ها در backoff باشند که آن‌وقت محدودیت نادیده گرفته می‌شود تا
   ربات کامل متوقف نشود.

لایه ۲ فقط برای حساب‌هایی اجرا می‌شود که لایه ۱ برایشان چیزی نداد — یعنی
نیتر دیگر تنها راه نیست، فقط یک پشتیبان است.
"""
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import config
from sources.base import parse_rss, clean_text

log = logging.getLogger("src.twitter")

_STATE_PATH = os.path.join("data", "twitter_state.json")
_state = {"base": "", "base_at": 0, "cursor": 0}
_loaded = False

BASE_TTL = 3600      # هر یک ساعت آینه را دوباره می‌سنجیم
FEED_TIMEOUT = 12
FALLBACK_TIMEOUT = 8          # آینه کمکی نباید کل سیکل را معطل کند
ACCOUNT_COOLDOWN = 1800       # حسابی که هیچ آینه‌ای ندادش، ۳۰ دقیقه کنار می‌رود
WORKERS = 8          # چند حساب همزمان

SYNDICATION_TIMEOUT = 10

# backoff نمایی برای آینه‌های خراب — تا این سقف بالا می‌رود
MIRROR_BACKOFF_BASE = 300        # ۵ دقیقه اولین شکست
MIRROR_BACKOFF_MAX = 6 * 3600    # حداکثر ۶ ساعت

# جملاتی که یعنی «این فید واقعی نیست»
JUNK_MARKERS = (
    "not yet whitelisted",
    "rate limit",
    "instance has been",
    "error retrieving",
    "tweets not found",
    "user not found",
    "making sure you",
    "just a moment",
    "enable javascript",
)


# ------------------------------------------------------------------ state
def _load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            _state.update(json.load(f))
    except Exception:
        pass


def _save():
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(_state, f)
    except Exception as e:
        log.debug("state save failed: %s", e)


# ------------------------------------------------------------- سلامت آینه‌ها
def _mirror_health():
    _load()
    return _state.setdefault("mirror_health", {})


def _mirror_is_backed_off(base, health):
    info = health.get(base)
    if not info:
        return False
    return time.time() < info.get("until", 0)


def _mirror_record(base, ok):
    health = _mirror_health()
    info = health.setdefault(base, {"fails": 0, "until": 0})
    if ok:
        info["fails"] = 0
        info["until"] = 0
    else:
        info["fails"] = info.get("fails", 0) + 1
        delay = min(MIRROR_BACKOFF_MAX, MIRROR_BACKOFF_BASE * (2 ** (info["fails"] - 1)))
        info["until"] = time.time() + delay
        log.info("آینه %s به مدت %d دقیقه کنار گذاشته شد (شکست پیاپی: %d)",
                 base, delay // 60, info["fails"])
    _save()


# ------------------------------------------------------------------ helpers
def feed_url(base, user):
    """آدرس فید یک حساب روی یک آینه."""
    b = (base or "").rstrip("/")
    u = (user or "").lstrip("@")
    if "twitter/user" in b or "rsshub" in b:
        return b + "/" + u
    return b + "/" + u + "/rss"


def is_junk(entry):
    """آیا این آیتم پیام خطای آینه است، نه توییت واقعی؟"""
    text = ((entry.get("title") or "") + " " + (entry.get("summary") or "")).lower()
    if not text.strip():
        return True
    return any(m in text for m in JUNK_MARKERS)


def clean_entries(entries):
    """فقط توییت‌های واقعی."""
    return [e for e in (entries or []) if not is_junk(e)]


# --------------------------------------------------- عکس و متن توییت
def fix_image(url):
    """لینک عکس نیتر را به لینک مستقیم توییتر تبدیل می‌کند.

    نیتر عکس‌ها را پراکسی می‌کند (…/pic/card_img%2F…) که تلگرام اغلب
    نمی‌تواند بردارد؛ نسخه اصلی روی pbs.twimg.com همیشه کار می‌کند.
    """
    if not url:
        return None
    if "/pic/" not in url:
        return url
    try:
        from urllib.parse import unquote
        tail = unquote(url.split("/pic/", 1)[1]).lstrip("/")
    except Exception:
        return url
    if tail.startswith("http"):
        return tail
    if tail.startswith("orig/"):
        tail = tail[5:]
    return "https://pbs.twimg.com/" + tail


_CARD_SPLIT = re.compile(r"\n\s*Link\s*\n", re.I)
_SHORTLINK = re.compile(r"\bhttps?://\S+", re.I)
# لینک بدون http مثل piped.video/watch?v=… یا inews.co.uk/sport/…
_BARE_LINK = re.compile(
    r"\b[\w.-]+\.(?:com|co\.uk|net|org|io|tv|it|fr|de|es|video|me|ly|gg)/\S*", re.I
)
_DOMAIN_LINE = re.compile(r"^[\w.-]+\.(com|co\.uk|net|org|io|tv|it|fr|de)\S*$", re.I)
# توییت ویدیویی در نیتر عکس ندارد ولی poster دارد
_POSTER = re.compile(r'poster="([^"]+)"', re.I)
_ANY_IMG = re.compile(r'src="([^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', re.I)


def tweet_image(entry):
    """عکس توییت — اگر ویدیو باشد از پوستر ویدیو استفاده می‌کند."""
    img = entry.get("image")
    if not img:
        html = entry.get("summary") or ""
        m = _POSTER.search(html) or _ANY_IMG.search(html)
        if m:
            img = m.group(1)
    if img and img.startswith("/"):
        img = (_state.get("base") or "").rstrip("/") + img
    return fix_image(img)


def _dedupe_parts(text):
    """نیتر اول خلاصه توییت را می‌آورد بعد متن کامل را — تکراری حذف می‌شود."""
    parts = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    keep = []
    for i, p in enumerate(parts):
        head = p[:60]
        if any(j != i and len(q) > len(p) and q.startswith(head) for j, q in enumerate(parts)):
            continue
        if p in keep:
            continue
        keep.append(p)
    return "\n\n".join(keep)


def tweet_text(entry):
    """متن تمیز توییت — بدون کارت پیش‌نمایش لینک و بدون تکرار."""
    title = clean_text(entry.get("title") or "")
    body = clean_text(entry.get("summary") or "") or title

    body = _CARD_SPLIT.split(body)[0]          # هر چه بعد از خط "Link" است کارت لینک است
    body = _SHORTLINK.sub(" ", body)
    body = _BARE_LINK.sub(" ", body)
    lines = [l.strip() for l in body.split("\n")]
    lines = [l for l in lines if not _DOMAIN_LINE.match(l) and l.lower() != "link"]
    body = _dedupe_parts("\n".join(lines)).strip()

    return body or title


def tweet_age_hours(entry):
    """سن توییت بر حسب ساعت — اگر تاریخ نداشت None."""
    raw = (entry.get("published") or "").strip()
    if not raw:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(raw)
    except Exception:
        return None
    if dt is None:
        return None
    try:
        import datetime as _dt
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        now = _dt.datetime.now(_dt.timezone.utc)
        return max(0.0, (now - dt).total_seconds() / 3600.0)
    except Exception:
        return None


def tweet_is_noise(text):
    """توییت‌های یک‌خطی/عکسی/ویدیویی که خبر نیستند."""
    t = (text or "").strip()
    core = re.sub(r"^\W+|\W+$", "", re.sub(r"\b(video|photo|gallery|link)\b", " ", t, flags=re.I))
    if len(core) < getattr(config, "TWEET_MIN_CHARS", 60):
        return True
    if len([w for w in re.split(r"\s+", core) if w]) < getattr(config, "TWEET_MIN_WORDS", 8):
        return True
    return False


def read_feed(base, user, timeout=FEED_TIMEOUT):
    """خواندن فید یک حساب از یک آینه — خروجی: لیست توییت‌های واقعی."""
    try:
        return clean_entries(parse_rss(feed_url(base, user), timeout=timeout))
    except Exception as e:
        log.debug("@%s on %s failed: %s", user, base, e)
        return []


def _accounts():
    tier1 = [a.lstrip("@") for a in config.TWITTER_TIER1 if a.strip()]
    everyone = [a.lstrip("@") for a in config.TWITTER_ACCOUNTS if a.strip()]
    rest = [a for a in everyone if a.lower() not in {t.lower() for t in tier1}]
    return tier1, rest


def _lfc_only(user):
    return user.lower() in {a.lstrip("@").lower() for a in config.TWITTER_LFC_ONLY}


def _is_relevant(text, user):
    """حساب‌های مختص لیورپول فیلتر کلمه‌ای نمی‌خورند؛ بقیه می‌خورند."""
    if _lfc_only(user):
        return True
    if not config.ROMANO_KEYWORDS:
        return True
    low = (text or "").lower()
    return any(k.lower() in low for k in config.ROMANO_KEYWORDS)


def canonical(link, user):
    m = re.search(r"/status(?:es)?/(\d+)", link or "")
    if m:
        return "https://x.com/" + user.lstrip("@") + "/status/" + m.group(1)
    return link


# --------------------------------------------------- لایه ۱: سندیکیشن مستقیم
_SYNDICATION_URL = "https://cdn.syndication.twimg.com/timeline/profile"
_SYNDICATION_HEADERS = {
    "User-Agent": getattr(config, "USER_AGENT", "Mozilla/5.0"),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def _twitter_date_to_rfc822(raw):
    """created_at توییتر (مثلاً Wed Oct 10 20:19:24 +0000 2018) را به فرمت
    استانداردی تبدیل می‌کند که tweet_age_hours() همین حالا می‌فهمد."""
    if not raw:
        return ""
    try:
        from datetime import datetime
        from email.utils import format_datetime
        dt = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
        return format_datetime(dt)
    except Exception:
        return raw


def _tweet_media(node):
    ext = node.get("extended_entities") or node.get("entities") or {}
    for m in ext.get("media", []) or []:
        url = m.get("media_url_https") or m.get("media_url")
        if url:
            return url
    return None


def _tweet_author(node):
    """نویسنده واقعی این آبجکت توییت‌مانند را پیدا می‌کند (اگر پیدا شود).

    لازم است چون پاسخ سندیکیشن ممکن است شامل توییت‌های نقل‌قول‌شده/ریتوییت‌شده
    از حساب‌های دیگر هم باشد؛ این‌ها نباید به‌جای توییت خودِ حساب حساب شوند.
    """
    for path in (
        ("core", "user_results", "result", "legacy", "screen_name"),
        ("user_results", "result", "legacy", "screen_name"),
        ("user", "screen_name"),
    ):
        cur = node
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok and isinstance(cur, str):
            return cur
    return None


def _extract_tweets(node, found=None):
    """به‌صورت بازگشتی هر آبجکتی که شبیه توییت واقعی است را پیدا می‌کند.

    چون ساختار این endpoint رسمی مستند نیست و ممکن است هر زمان بدون اطلاع
    عوض شود، به‌جای وابستگی به یک مسیر ثابت در JSON، کل درخت گشته می‌شود.
    """
    if found is None:
        found = []
    if isinstance(node, dict):
        text = node.get("full_text") or node.get("text")
        tid = node.get("id_str") or node.get("rest_id")
        if text and tid and re.match(r"^\d+$", str(tid)):
            found.append(node)
        for v in node.values():
            _extract_tweets(v, found)
    elif isinstance(node, list):
        for v in node:
            _extract_tweets(v, found)
    return found


def syndication_fetch(user, timeout=SYNDICATION_TIMEOUT):
    """لایه ۱ — مستقیم از سرور خود توییتر، بدون هیچ آینه‌ای.

    بهترین حالت: کاملاً پایدار چون واسطه ندارد. بدترین حالت: پاسخ خالی یا
    ساختار غیرمنتظره — که هر دو بی‌خطر مدیریت می‌شوند و لایه ۲ (نیتر) جایگزین
    می‌شود.
    """
    try:
        r = requests.get(
            _SYNDICATION_URL,
            params={"screen_name": user.lstrip("@"), "showReplies": "false"},
            headers=_SYNDICATION_HEADERS,
            timeout=timeout,
        )
        if r.status_code != 200 or not r.text.strip():
            log.debug("syndication @%s -> HTTP %s", user, r.status_code)
            return []
        data = r.json()
    except Exception as e:
        log.debug("syndication @%s failed: %s", user, e)
        return []

    raw_tweets = _extract_tweets(data)
    seen, out = set(), []
    for t in raw_tweets:
        tid = t.get("id_str") or t.get("rest_id")
        if not tid or tid in seen:
            continue
        author = _tweet_author(t)
        if author and author.lower() != user.lstrip("@").lower():
            continue    # توییت نقل‌قول‌شده/ریتوییت‌شده از حساب دیگر — رد می‌شود
        seen.add(tid)
        text = t.get("full_text") or t.get("text") or ""
        out.append(
            {
                "title": text,
                "link": "https://x.com/%s/status/%s" % (user.lstrip("@"), tid),
                "summary": text,
                "image": _tweet_media(t),
                "published": _twitter_date_to_rfc822(t.get("created_at", "")),
            }
        )

    def _sort_key(e):
        age = tweet_age_hours(e)
        return age if age is not None else 999999

    try:
        out.sort(key=_sort_key)
    except Exception:
        pass
    return out


def _read_many_syndication(users, timeout=SYNDICATION_TIMEOUT):
    result = {}
    if not users:
        return result
    with ThreadPoolExecutor(max_workers=min(len(users), WORKERS)) as pool:
        futures = {pool.submit(syndication_fetch, u, timeout): u for u in users}
        for fut in as_completed(futures):
            u = futures[fut]
            try:
                result[u] = fut.result()
            except Exception as e:
                log.debug("syndication @%s failed: %s", u, e)
                result[u] = []
    return result


# --------------------------------------------------- لایه ۲: آینه‌های نیتر
def rank_bases(probe_user=None, timeout=FEED_TIMEOUT):
    """همه آینه‌ها را موازی می‌سنجد، امتیاز سلامت‌شان را ثبت می‌کند و
    مرتب‌شده برمی‌گرداند.

    خروجی: [(base, تعداد توییت واقعی, ثانیه), ...] از بهترین به بدترین.
    """
    tier1, rest = _accounts()
    user = probe_user or (tier1 or rest or ["FabrizioRomano"])[0]
    bases = [b.strip() for b in config.NITTER_BASES if b.strip()]
    if not bases:
        return []

    def probe(base):
        t0 = time.time()
        entries = read_feed(base, user, timeout=timeout)
        _mirror_record(base, ok=len(entries) >= 1)
        return (base, len(entries), round(time.time() - t0, 1))

    out = []
    with ThreadPoolExecutor(max_workers=min(len(bases), WORKERS)) as pool:
        for fut in as_completed([pool.submit(probe, b) for b in bases]):
            try:
                out.append(fut.result())
            except Exception as e:
                log.debug("probe failed: %s", e)

    # اول آنی که بیشترین توییت واقعی داد، بین مساوی‌ها سریع‌ترین
    out.sort(key=lambda r: (-r[1], r[2]))
    return out


def pick_base(force=False):
    """بهترین آینه سالم (بیرون از backoff) را انتخاب و تا BASE_TTL ذخیره می‌کند."""
    _load()
    now = time.time()
    if not force and _state.get("base") and now - _state.get("base_at", 0) < BASE_TTL:
        return _state["base"]

    ranked = rank_bases()
    health = _mirror_health()
    alive = [r for r in ranked if not _mirror_is_backed_off(r[0], health)]
    # اگر همه آینه‌ها در backoff بودند، محدودیت را نادیده می‌گیریم تا کاملاً
    # بی‌آینه نمانیم — بهتر است آینه‌ی نه‌چندان تازه امتحان شود تا هیچ‌کدام
    pool = alive or ranked

    # حداقل ۳ توییت واقعی = آینه سالم
    healthy = [r for r in pool if r[1] >= 3]

    if healthy:
        base = healthy[0][0]
        _state.update({"base": base, "base_at": now})
        _save()
        log.info("آینه فعال توییتر: %s (%d توییت، %ss)",
                 base, healthy[0][1], healthy[0][2])
        return base

    _state.update({"base": "", "base_at": now})
    _save()
    log.error("هیچ آینه سالمی پیدا نشد — python check_mirrors.py را بزن")
    return ""


def _due_accounts():
    """درجه‌یک‌ها همیشه + چند حساب بعدی از نوبت."""
    _load()
    tier1, rest = _accounts()
    n = max(0, config.ACCOUNTS_PER_CYCLE)
    if not rest or n == 0:
        return tier1

    cur = _state.get("cursor", 0) % len(rest)
    picked = [rest[(cur + i) % len(rest)] for i in range(min(n, len(rest)))]
    _state["cursor"] = (cur + len(picked)) % len(rest)
    _save()
    return tier1 + picked


def _read_many(base, users):
    """چند حساب را موازی می‌خواند — خروجی: {user: entries}."""
    result = {}
    if not users:
        return result
    with ThreadPoolExecutor(max_workers=min(len(users), WORKERS)) as pool:
        futures = {pool.submit(read_feed, base, u): u for u in users}
        for fut in as_completed(futures):
            u = futures[fut]
            try:
                result[u] = fut.result()
            except Exception as e:
                log.debug("@%s failed: %s", u, e)
                result[u] = []

    # حساب‌هایی که خالی ماندند (مثلاً 429) — همه‌ی آینه‌های کمکی با هم
    now = time.time()
    cool = _state.setdefault("cooldown", {})
    missing = [
        u for u in users
        if not result.get(u) and now - float(cool.get(u.lower(), 0)) > ACCOUNT_COOLDOWN
    ]
    if missing:
        others = [b for b in config.NITTER_BASES if b and b != base][:2]
        pairs = [(alt, u) for u in missing for alt in others]
        with ThreadPoolExecutor(max_workers=min(len(pairs), WORKERS)) as pool:
            futures = {
                pool.submit(read_feed, alt, u, FALLBACK_TIMEOUT): (alt, u)
                for alt, u in pairs
            }
            for fut in as_completed(futures):
                alt, u = futures[fut]
                if result.get(u):
                    continue
                try:
                    entries = fut.result()
                except Exception:
                    entries = []
                if entries:
                    result[u] = entries
                    log.info("آینه کمکی %s برای @%s جواب داد", alt, u)
        for u in missing:
            if not result.get(u):
                cool[u.lower()] = now      # تا مدتی سراغش نمی‌رویم
                log.info("@%s جواب نداد — %d دقیقه کنار گذاشته شد", u, ACCOUNT_COOLDOWN // 60)
        _save()
    return result


# ------------------------------------------------------------------ fetch
def fetch(limit=6):
    users = _due_accounts()
    if not users:
        return []
    t0 = time.time()

    # لایه ۱: مستقیم از خود توییتر — بدون آینه
    use_syndication = getattr(config, "ENABLE_TWITTER_SYNDICATION", True)
    feeds = _read_many_syndication(users) if use_syndication else {}
    synd_hits = [u for u in users if feeds.get(u)]

    # لایه ۲: آینه‌های نیتر — فقط برای حساب‌هایی که لایه ۱ چیزی نداد
    missing = [u for u in users if not feeds.get(u)]
    if missing:
        base = pick_base()
        if base:
            mirror_feeds = _read_many(base, missing)
            for u, entries in mirror_feeds.items():
                if entries:
                    feeds[u] = entries
            dead = [u for u in missing if not feeds.get(u)]
            if len(dead) > len(missing) * 0.6:
                log.warning("آینه %s جواب نمی‌دهد (%d از %d خالی) — آینه دیگری امتحان می‌شود",
                            base, len(dead), len(missing))
                new_base = pick_base(force=True)
                still_missing = [u for u in missing if not feeds.get(u)]
                if new_base and new_base != base and still_missing:
                    mirror_feeds = _read_many(new_base, still_missing)
                    for u, entries in mirror_feeds.items():
                        if entries:
                            feeds[u] = entries

    log.info("توییتر: %d حساب در %ss (سندیکیشن مستقیم: %d، نیتر: %d)",
             len(users), round(time.time() - t0, 1), len(synd_hits), len(users) - len(synd_hits))

    out = []
    for user in users:
        if len(out) >= limit:
            break
        for e in (feeds.get(user) or [])[:3]:
            max_age = getattr(config, "TWEET_MAX_AGE_HOURS", 24)
            age = tweet_age_hours(e)
            if max_age and age is not None and age > max_age:
                log.debug("رد شد (قدیمی %.0fساعت): @%s", age, user)
                continue
            text = tweet_text(e)
            if not text or text.startswith("RT "):
                continue
            if tweet_is_noise(text):
                log.info("رد شد (توییت کوتاه/مدیا): @%s — %s", user, text[:50].replace("\n", " "))
                continue
            if not _is_relevant(text, user):
                continue
            out.append(
                {
                    "source": "Twitter",
                    "source_tag": config.display_name(user),
                    "handle": "@" + user,
                    "url": canonical(e.get("link"), user),
                    "title": text[:200],
                    "body": text,
                    "image": tweet_image(e),
                    "priority": True,
                }
            )
            if len(out) >= limit:
                break

    return out
