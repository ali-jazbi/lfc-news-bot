"""منبع توییتر — چندین حساب، موازی، با انتخاب هوشمند آینه.

سه درس از تست‌های واقعی:

۱) بعضی آینه‌ها «جواب می‌دهند» ولی محتوایشان آشغال است
   (مثلاً xcancel که می‌نویسد: RSS reader not yet whitelisted!).
   پس فقط «خالی نبودن» کافی نیست — محتوا هم اعتبارسنجی می‌شود.

۲) خواندن ۱۲ حساب پشت سر هم با آینه کند = چند دقیقه هنگ.
   پس همه حساب‌ها موازی خوانده می‌شوند با تایم‌اوت کوتاه.

۳) آینه‌ها بی‌ثبات‌اند. بهترین آینه با امتیاز انتخاب می‌شود، نه اولین جوابگو.
"""
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

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


# ------------------------------------------------------------------ mirror
def rank_bases(probe_user=None, timeout=FEED_TIMEOUT):
    """همه آینه‌ها را موازی می‌سنجد و مرتب‌شده برمی‌گرداند.

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
    """بهترین آینه را انتخاب و تا BASE_TTL ذخیره می‌کند."""
    _load()
    now = time.time()
    if not force and _state.get("base") and now - _state.get("base_at", 0) < BASE_TTL:
        return _state["base"]

    ranked = rank_bases()
    # حداقل ۳ توییت واقعی = آینه سالم
    healthy = [r for r in ranked if r[1] >= 3]

    if healthy:
        base = healthy[0][0]
        _state.update({"base": base, "base_at": now})
        _save()
        log.info("\u0622ینه فعال توییتر: %s (%d توییت، %ss)",
                 base, healthy[0][1], healthy[0][2])
        return base

    _state.update({"base": "", "base_at": now})
    _save()
    log.error("\u0647یچ آینه سالمی پیدا نشد — python check_mirrors.py را بزن")
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


# ------------------------------------------------------------------ fetch
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
                    log.info("\u0622\u06cc\u0646\u0647 \u06a9\u0645\u06a9\u06cc %s \u0628\u0631\u0627\u06cc @%s \u062c\u0648\u0627\u0628 \u062f\u0627\u062f", alt, u)
        for u in missing:
            if not result.get(u):
                cool[u.lower()] = now      # تا مدتی سراغش نمی‌رویم
                log.info("@%s \u062c\u0648\u0627\u0628 \u0646\u062f\u0627\u062f \u2014 %d \u062f\u0642\u06cc\u0642\u0647 \u06a9\u0646\u0627\u0631 \u06af\u0630\u0627\u0634\u062a\u0647 \u0634\u062f", u, ACCOUNT_COOLDOWN // 60)
        _save()
    return result


def fetch(limit=6):
    base = pick_base()
    if not base:
        return []

    users = _due_accounts()
    t0 = time.time()
    feeds = _read_many(base, users)
    dead = [u for u in users if not feeds.get(u)]

    # اگر بیشتر حساب‌ها خالی برگشتند یعنی آینه خراب شده — یک بار عوض می‌کنیم
    if users and len(dead) > len(users) * 0.6:
        log.warning("\u0622ینه %s جواب نمی‌دهد (%d از %d خالی) — آینه دیگری امتحان می‌شود",
                    base, len(dead), len(users))
        new_base = pick_base(force=True)
        if new_base and new_base != base:
            base = new_base
            feeds = _read_many(base, users)

    log.info("\u062aوییتر: %d حساب در %ss (%s)",
             len(users), round(time.time() - t0, 1), ", ".join(users[:6]))

    out = []
    for user in users:
        if len(out) >= limit:
            break
        for e in (feeds.get(user) or [])[:3]:
            max_age = getattr(config, "TWEET_MAX_AGE_HOURS", 24)
            age = tweet_age_hours(e)
            if max_age and age is not None and age > max_age:
                log.debug("\u0631\u062f \u0634\u062f (\u0642\u062f\u06cc\u0645\u06cc %.0f\u0633\u0627\u0639\u062a): @%s", age, user)
                continue
            text = tweet_text(e)
            if not text or text.startswith("RT "):
                continue
            if tweet_is_noise(text):
                log.info("\u0631\u062f \u0634\u062f (\u062a\u0648\u06cc\u06cc\u062a \u06a9\u0648\u062a\u0627\u0647/\u0645\u062f\u06cc\u0627): @%s \u2014 %s", user, text[:50].replace("\n", " "))
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
