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
import health
from sources.base import (
    parse_rss,
    clean_text,
    images_in_html,
    extract_tweet_id_from_link,
)

log = logging.getLogger("src.twitter")

_STATE_PATH = os.path.join("data", "twitter_state.json")
_state = {"base": "", "base_at": 0, "cursor": 0}
_loaded = False

BASE_TTL = 3600      # هر یک ساعت آینه را دوباره می‌سنجیم
FEED_TIMEOUT = 12
FALLBACK_TIMEOUT = 8          # آینه کمکی نباید کل سیکل را معطل کند
# حسابی که (بدون 429) چیزی نداد، فقط این مدت کنار می‌رود تا سیکل بعد دوباره
# خوانده شود — دیگر ۳۰ دقیقه محرومیت نداریم که خبر از دست برود.
ACCOUNT_SKIP_SECONDS = 60
WORKERS = 4          # چند حساب همزمان — کمتر تا نیتر 429 ندهد
INTER_ACCOUNT_DELAY = 0.25    # فاصله کوتاه بین درخواست حساب‌ها (۲۹ حساب = ~۷ ثانیه)
BASE_SWITCH_THRESHOLD = 0.5   # اگر بیش از نیمی از حساب‌ها خالی ماندند آینه عوض کن
ALBUM_MAX = 10                # سقف آلبوم تلگرام

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
        log.info("mirror %s put on backoff for %d min (consecutive fails: %d)",
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
    دو شکل URL از نیتر می‌آید:
      …/pic/media%2F…            → نسبی، به pbs.twimg.com/ اضافه می‌شود
      …/pic/pbs.twimg.com%2F…    → کامل (فقط بدون scheme)، باید https:// بگیرد
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
    if tail.startswith("pbs.twimg.com/"):
        return "https://" + tail
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

# پوستر ویدیوی خودِ توییت — این یعنی «توییت ویدیویی است»
_IMG_VIDEO_THUMB = re.compile(
    r"(?:ext_tw_video_thumb|amplify_video_thumb|video_thumb)", re.I
)
# کارت لینک و آواتار/بک‌گراند — نباید در آلبوم بیایند
_IMG_CARD = re.compile(r"(?:card_img|profile_images|profile_banners)", re.I)


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


def _own_media_urls(entry, max_imgs=ALBUM_MAX):
    """عکس‌های خودِ توییت از خلاصه نیتر.

    قانون: همه <img> های قبل از اولین <blockquote> که الگوی media دارند.
    عکس توییتِ نقل‌قولی داخل <blockquote> است و هرگز در آلبوم نمی‌آید.
    کارت لینک (card_img) و آواتار/بک‌گراند (profile_*) حذف می‌شوند.

    نکته: دسته‌بندی روی URL خام نیتر انجام می‌شود (هنوز media%2F دارد) چون
    fix_image() آن را به pbs.twimg.com/media/… تبدیل می‌کند و %2F از بین می‌رود.
    """
    html = entry.get("summary") or ""
    if not html:
        return []
    own_part = re.split(r"<blockquote>", html, maxsplit=1)[0]
    out, seen = [], set()
    for u in images_in_html(own_part, max_imgs=max_imgs * 3):
        if _IMG_CARD.search(u):
            continue
        if "media%2F" not in u and "media/" not in u:
            continue
        fixed = fix_image(u)
        if not fixed or fixed in seen:
            continue
        seen.add(fixed)
        out.append(fixed)
        if len(out) >= max_imgs:
            break
    return out


def tweet_has_video(entry):
    """آیا خلاصه پوستر ویدیوی خودِ توییت را دارد؟"""
    return bool(_IMG_VIDEO_THUMB.search(entry.get("summary") or ""))




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
        log.info("active twitter mirror: %s (%d tweets, %ss)",
                 base, healthy[0][1], healthy[0][2])
        return base

    _state.update({"base": "", "base_at": now})
    _save()
    log.error("no healthy mirror found — run python check_mirrors.py")
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


def _read_feed_diag(base, user, timeout=FEED_TIMEOUT):
    """مانند read_feed ولی وضعیت دقیق را هم برمی‌گرداند.

    خروجی: (entries, why) که why یکی از ok | rate_limit | whitelist | empty | network
    است. 429 نیتر همیشه HTTP 429 نیست — گاهی صفحه 200 با متن «rate limit» می‌دهد،
    پس هم کد وضعیت و هم متن بدنه چک می‌شود.
    """
    url = feed_url(base, user)
    try:
        r = requests.get(url, headers={"User-Agent": config.USER_AGENT},
                         timeout=timeout, allow_redirects=True)
    except Exception:
        return [], "network"
    if r.status_code == 429:
        return [], "rate_limit"
    if r.status_code != 200:
        return [], "empty"
    raw = r.text
    low = raw.lower()
    if "rate limit" in low:
        return [], "rate_limit"
    try:
        entries = clean_entries(parse_rss(raw, raw=raw))
    except Exception:
        return [], "parse"
    if not entries:
        if "whitelist" in low:
            return [], "whitelist"
        return [], "empty"
    _mirror_record(base, ok=True)
    return entries, "ok"


def _read_many(base, users):
    """چند حساب را موازی می‌خواند — خروجی: (result, rl_flagged).

    سیاست «هیچ خبری از دست نره»:
      - 429 (rate_limit) را با «بی‌خبری» یکی نمی‌گیریم. حساب 429 را در سیکلِ
        بعد فوراً دوباره می‌خوانیم — محرومیت ۳۰ دقیقه‌ای دیگر نداریم.
      - حسابی که واقعاً (بدون 429) چیزی نداد فقط ACCOUNT_SKIP_SECONDS (۶۰ ثانیه)
        کنار می‌رود و بعد دوباره خوانده می‌شود. db.is_duplicate جلوی تکرار خبر
        شناخته‌شده را می‌گیرد، پس چیزی از دست نمی‌رود.
    """
    result = {}
    rl_flagged, missing = [], []
    if not users:
        return result, rl_flagged
    with ThreadPoolExecutor(max_workers=min(len(users), WORKERS)) as pool:
        futures = {pool.submit(_read_feed_diag, base, u): u for u in users}
        for fut in as_completed(futures):
            u = futures[fut]
            entries, why = fut.result()
            if why == "rate_limit":
                rl_flagged.append(u)
            if entries:
                result[u] = entries
            else:
                missing.append(u)
            time.sleep(INTER_ACCOUNT_DELAY)   # فاصله کوتاه بین حساب‌ها — ضد 429

    now = time.time()
    cool = _state.setdefault("cooldown", {})
    # 429 ≠ بی‌خبری: با یک زمان بسیار قدیمی علامت می‌زنیم تا سیکل بعد فوراً بخواند
    for u in rl_flagged:
        cool[u.lower()] = now - 1_000_000

    fresh_missing = [
        u for u in missing
        if now - float(cool.get(u.lower(), 0)) > ACCOUNT_SKIP_SECONDS
    ]
    if fresh_missing:
        others = [b for b in config.NITTER_BASES if b and b != base][:2]
        pairs = [(alt, u) for u in fresh_missing for alt in others]
        with ThreadPoolExecutor(max_workers=min(len(pairs), WORKERS)) as pool:
            futures = {
                pool.submit(_read_feed_diag, alt, u, FALLBACK_TIMEOUT): (alt, u)
                for alt, u in pairs
            }
            for fut in as_completed(futures):
                alt, u = futures[fut]
                entries, why = fut.result()
                if entries:
                    result[u] = entries
                    log.info("backup mirror %s responded for @%s", alt, u)
        for u in fresh_missing:
            if not result.get(u):
                cool[u.lower()] = now     # فقط یک سیکل (≈۶۰ ثانیه) صبر
                log.info("@%s gave nothing - retrying next cycle", u)
    _save()
    return result, rl_flagged


# --------------------------------------- غنی‌سازی رسانه (fxtwitter/vxtwitter)
# کش رسانه: tweet_id -> (زمان, payload). فقط برای توییت‌هایی که رسانه دارند
# فراخوانی می‌شود تا API بیهوده اذیت نشود.
_ENRICH_CACHE = {}

def _enrich_tweet(handle, tweet_id, timeout=12):
    """مستقیم از fxtwitter/vxtwitter — خروجی None اگر رسانه نداشت یا خطا داد."""
    now = time.time()
    hit = _ENRICH_CACHE.get(tweet_id)
    if hit and now - hit[0] < getattr(config, "TWITTER_ENRICH_TTL", 900):
        return hit[1]
    payload = _enrich_fxtwitter(handle, tweet_id, timeout) \
        or _enrich_vxtwitter(handle, tweet_id, timeout)
    _ENRICH_CACHE[tweet_id] = (now, payload)
    if len(_ENRICH_CACHE) > 256:
        _ENRICH_CACHE.pop(next(iter(_ENRICH_CACHE)))   # حافظه سبک
    return payload


def _enrich_fxtwitter(handle, tweet_id, timeout=12):
    """fxtwitter: لینک مستقیم ویدیو (video.twimg.com/...mp4) و عکس‌ها را می‌دهد."""
    try:
        r = requests.get(
            "https://api.fxtwitter.com/%s/status/%s" % (handle.lstrip("@"), tweet_id),
            headers={"User-Agent": config.USER_AGENT}, timeout=timeout,
        )
        if r.status_code != 200:
            return None
        media = (r.json().get("tweet") or {}).get("media") or {}
        all_media = media.get("all") or []
        if not all_media:
            return None
        videos = [m for m in all_media if m.get("type") == "video"]
        photos = [m for m in all_media if m.get("type") == "photo"]
        return {
            "video_url": videos[0].get("url") if videos else None,
            "thumbnail_url": videos[0].get("thumbnail_url") if videos else None,
            "media_urls": [m.get("url") for m in photos if m.get("url")],
            "source": "fxtwitter",
        }
    except Exception as e:
        log.debug("fxtwitter %s failed: %s", tweet_id, e)
        return None


def _enrich_vxtwitter(handle, tweet_id, timeout=12):
    """vxtwitter: همه عکس‌ها (mediaURLs) را می‌دهد — جایگزین fxtwitter."""
    try:
        r = requests.get(
            "https://api.vxtwitter.com/%s/status/%s" % (handle.lstrip("@"), tweet_id),
            headers={"User-Agent": config.USER_AGENT}, timeout=timeout,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        media_urls = [u for u in (data.get("mediaURLs") or []) if u]
        if not media_urls and not data.get("mediaType"):
            return None
        video_url = media_urls[0] if data.get("mediaType") == "video" and media_urls else None
        return {"video_url": video_url, "media_urls": media_urls, "source": "vxtwitter"}
    except Exception as e:
        log.debug("vxtwitter %s failed: %s", tweet_id, e)
        return None


def _attach_media(item, entry, user):
    """item را با عکس/آلبوم/ویدیو پر می‌کند.

    عکس‌ها مستقیم از RSS نیتر می‌آیند (سبک و بدون API اضافه). فقط توییت‌هایی
    که پوستر ویدیو دارند به fxtwitter/vxtwitter می‌روند تا لینک mp4 بگیرند —
    توییت عکسی را بیهوده اذیت نمی‌کنیم.
    """
    if getattr(config, "ENABLE_TWITTER_MEDIA", True):
        item["images"] = _own_media_urls(entry)
        if not item.get("image"):
            item["image"] = item["images"][0] if item["images"] else None

    if getattr(config, "ENABLE_TWITTER_VIDEO", True) and tweet_has_video(entry):
        tid = extract_tweet_id_from_link(entry.get("link")) \
            or extract_tweet_id_from_link(item.get("url"))
        if tid:
            got = _enrich_tweet(user, tid)
            if got:
                if got.get("video_url"):
                    item["video_url"] = got["video_url"]
                    item["video_thumb"] = got.get("thumbnail_url") or item.get("image")
                if got.get("media_urls") and not item.get("images"):
                    item["images"] = got["media_urls"][:getattr(config, "TWITTER_ALBUM_MAX", 10)]


# ------------------------------------------------------------------ fetch
def fetch(limit=6):
    users = _due_accounts()
    if not users:
        return []
    t0 = time.time()

    # لایه ۱: سندیکیشن مستقیم توییتر — فعلاً بلاک شده، خاموش می‌ماند
    use_syndication = getattr(config, "ENABLE_TWITTER_SYNDICATION", False)
    feeds = _read_many_syndication(users) if use_syndication else {}
    missing = [u for u in users if not feeds.get(u)]
    rl_flagged = []

    # لایه ۲: آینه‌های نیتر — برای حساب‌هایی که لایه ۱ چیزی نداد
    if missing:
        base = pick_base()
        if base:
            mirror_feeds, rl_flagged = _read_many(base, missing)
            for u, entries in mirror_feeds.items():
                if entries:
                    feeds[u] = entries
            dead = [u for u in missing if not feeds.get(u)]
            # اگر بیشتر از آستانه حساب‌ها خالی ماندند → switching mirrors
            if dead and len(dead) > len(missing) * BASE_SWITCH_THRESHOLD:
                log.warning("mirror %s unresponsive (%d/%d) — switching mirrors",
                            base, len(dead), len(missing))
                new_base = pick_base(force=True)
                still_missing = [u for u in missing if not feeds.get(u)]
                if new_base and new_base != base and still_missing:
                    mirror_feeds, _ = _read_many(new_base, still_missing)
                    for u, entries in mirror_feeds.items():
                        if entries:
                            feeds[u] = entries

    log.info("twitter: %d accounts in %ss (429: %d)",
             len(users), round(time.time() - t0, 1), len(rl_flagged))
    if rl_flagged:
        health.record_counter("twitter_rl", len(rl_flagged))

    out = []
    for user in users:
        if len(out) >= limit:
            break
        for e in (feeds.get(user) or [])[:3]:
            max_age = getattr(config, "TWEET_MAX_AGE_HOURS", 24)
            age = tweet_age_hours(e)
            if max_age and age is not None and age > max_age:
                log.debug("skipped (%.0fh old): @%s", age, user)
                continue
            text = tweet_text(e)
            if not text or text.startswith("RT "):
                continue
            if tweet_is_noise(text):
                log.info("skipped (short tweet): @%s — %s",
                         user, text[:50].replace("\n", " "))
                continue
            if not _is_relevant(text, user):
                continue
            item = {
                "source": "Twitter",
                "source_tag": config.display_name(user),
                "handle": "@" + user,
                "url": canonical(e.get("link"), user),
                "title": text[:200],
                "body": text,
                "image": tweet_image(e),
                "priority": True,
            }
            _attach_media(item, e, user)   # عکس‌ها/آلبوم/ویدیو اینجا
            out.append(item)
            if len(out) >= limit:
                break

    return out
