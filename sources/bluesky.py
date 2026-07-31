"""منبع جدید: بلواسکای (AT Protocol) — جایگزین رسمی و پایدار برای پل‌های نیتر توییتر.

برخلاف نیتر (که آینه‌هایش مدام می‌میرند/فیلتر می‌شوند)، بلواسکای یک
آدرس API عمومی و رسمی دارد که نیازی به کلید یا لاگین ندارد:
    https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed

**فعال‌سازی**: این منبع فقط برای هندل‌هایی که در BLUESKY_HANDLES در .env
اضافه کنی کار می‌کند (مثال: someone.bsky.social). اگر خالی باشد این منبع
خودش را غیرفعال می‌کند — چون هیچ نگاشته‌ای از خبرنگاران توییتر → هندل بلواسکای
قابل حدس زدن نیست (باید دستی پیدا شود).
"""
import logging

import requests

import config
from sources.base import clean_text

log = logging.getLogger("src.bluesky")

API = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
TIMEOUT = 12
PER_ACCOUNT_LIMIT = 15


def _post_images(post):
    """عکس‌های پست را از روی قالب embed می‌کشد — فقط قالب‌های رایج عکس."""
    embed = post.get("embed") or {}
    t = embed.get("$type", "")
    imgs = []
    if t.startswith("app.bsky.embed.images"):
        for img in embed.get("images", []) or []:
            u = img.get("fullsize") or img.get("thumb")
            if u:
                imgs.append(u)
    elif t.startswith("app.bsky.embed.recordWithMedia"):
        media = embed.get("media") or {}
        for img in media.get("images", []) or []:
            u = img.get("fullsize") or img.get("thumb")
            if u:
                imgs.append(u)
    return imgs


def _fetch_author(handle, limit=PER_ACCOUNT_LIMIT):
    try:
        r = requests.get(API, params={"actor": handle, "limit": limit}, timeout=TIMEOUT)
        if r.status_code != 200:
            log.warning("bluesky @%s -> %s", handle, r.status_code)
            return []
        data = r.json()
    except Exception as e:
        log.warning("bluesky @%s failed: %s", handle, e)
        return []

    out = []
    for item in data.get("feed", []) or []:
        # ریتوییت/ریپلای را رد می‌کنیم — فقط پست مستقیم خود حساب می‌شود
        if item.get("reason"):
            continue
        post = item.get("post") or {}
        record = post.get("record") or {}
        if record.get("reply"):
            continue
        text = clean_text(record.get("text") or "")
        if not text:
            continue
        uri = post.get("uri") or ""
        rkey = uri.rsplit("/", 1)[-1] if uri else ""
        link = ("https://bsky.app/profile/" + handle + "/post/" + rkey) if rkey else None
        out.append(
            {
                "text": text,
                "link": link,
                "images": _post_images(post),
                "created": record.get("createdAt"),
            }
        )
    return out


def fetch(limit=6):
    handles = [h.strip().lstrip("@") for h in getattr(config, "BLUESKY_HANDLES", []) if h.strip()]
    if not handles:
        return []

    out = []
    for handle in handles:
        for e in _fetch_author(handle):
            text = e["text"]
            if len(text) < getattr(config, "TWEET_MIN_CHARS", 60):
                continue
            out.append(
                {
                    "source": "Bluesky",
                    "source_tag": config.display_name(handle.split(".")[0]),
                    "handle": "@" + handle,
                    "url": e["link"] or ("https://bsky.app/profile/" + handle),
                    "title": text[:200],
                    "body": text,
                    "image": (e["images"][0] if e["images"] else None),
                    "images": e["images"],
                    "priority": True,
                }
            )
            if len(out) >= limit:
                return out
    return out
