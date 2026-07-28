"""منبع ۱: سایت رسمی باشگاه — https://www.liverpoolfc.com/news

روش: صفحه لیست را می‌گیرد، لینک خبرها را درمی‌آورد، سپس هر خبر را با
متاتگ‌های og: (عنوان/توضیح/عکس) + پاراگراف‌های متن استخراج می‌کند.
اگر ساختار سایت عوض شد، فال‌بک Google News RSS خودکار فعال می‌شود.
"""
import logging
import re
from urllib.parse import urljoin

import config
from sources.base import http_get, soup_of, meta, clean_text

log = logging.getLogger("src.lfc")
GOOGLE_FALLBACK = (
    "https://news.google.com/rss/search?q=site:liverpoolfc.com+when:1d&hl=en-GB&gl=GB&ceid=GB:en"
)


_TITLE_TAIL = re.compile(
    r"\s*[-–|]\s*(Liverpool FC(\.com)?|Liverpool Football Club|LiverpoolFC\.com)\s*$",
    re.IGNORECASE,
)


def _clean_title(title):
    """دم تکراری «- Liverpool FC» را از عنوان می‌کند."""
    t = clean_text(title)
    for _ in range(2):
        t = _TITLE_TAIL.sub("", t).strip()
    return t


_WOMEN_MARKERS = (
    "lfc women",
    "liverpool fc women",
    "liverpool women",
    "women's super league",
    "womens super league",
    "barclays women",
)


def is_noise(title, url="", body=""):
    """گالری عکس، ویدئو، کویز، تبلیغ و مشابه ارزش پست کردن ندارند."""
    low = (title or "").lower()
    low_url = (url or "").lower()
    low_body = (body or "").lower()[:800]
    for kw in config.SKIP_KEYWORDS:
        if kw and kw.lower() in low:
            return kw
    if not config.INCLUDE_WOMEN:
        # گاهی تیتر اسم تیم بانوان را نمی‌آورد — لینک و متن را هم می‌بینیم
        if "/women" in low_url or "-women-" in low_url or low_url.rstrip("/").endswith("-women"):
            return "women"
        for mark in _WOMEN_MARKERS:
            if mark in low or mark in low_body:
                return "women"
    return None


def _article_links(limit=12):
    html = http_get(config.LFC_NEWS_URL)
    if not html:
        return []
    links, seen = [], set()
    for m in re.finditer(r'href="([^"]*/(?:news|article)/[^"?#]+)"', html):
        url = urljoin("https://www.liverpoolfc.com", m.group(1))
        if url.rstrip("/").endswith("/news"):
            continue
        if url in seen:
            continue
        seen.add(url)
        links.append(url)
        if len(links) >= limit:
            break
    return links


def _parse_article(url):
    html = http_get(url)
    if not html:
        return None
    s = soup_of(html)
    title = meta(s, "og:title") or (s.title.get_text(strip=True) if s.title else "")
    image = meta(s, "og:image")
    desc = meta(s, "og:description") or ""

    paras = []
    for p in s.find_all("p"):
        t = clean_text(p.get_text(" ", strip=True))
        if len(t) > 40 and "cookie" not in t.lower():
            paras.append(t)
        if len(" ".join(paras)) > 1800:
            break
    body = "\n".join(paras) or desc
    if not title or not body:
        return None
    return {
        "source": "LFC Official",
        "source_tag": "Liverpool FC",
        "url": url,
        "title": _clean_title(title),
        "body": body,
        "image": image,
    }


def _google_fallback(limit=5):
    from sources.base import parse_rss
    items = []
    for e in parse_rss(GOOGLE_FALLBACK)[:limit]:
        items.append(
            {
                "source": "LFC Official",
                "source_tag": "Liverpool FC",
                "url": e["link"],
                "title": _clean_title(e["title"]),
                "body": clean_text(e.get("summary", "")) or clean_text(e["title"]),
                "image": None,
            }
        )
    return items


def fetch(limit=6):
    out = []
    try:
        links = _article_links(limit=limit * 2)
    except Exception as e:
        log.warning("listing failed: %s", e)
        links = []

    for url in links:
        if len(out) >= limit:
            break
        try:
            art = _parse_article(url)
            if not art:
                continue
            why = is_noise(art["title"], art["url"], art.get("body") or art.get("summary") or "")
            if why:
                log.info("رد شد (%s): %s", why, art["title"][:60])
                continue
            out.append(art)
        except Exception as e:
            log.warning("article failed %s: %s", url, e)

    if not out:
        log.warning("پارس مستقیم سایت نتیجه نداد — فال‌بک Google News")
        try:
            out = [
                it for it in _google_fallback(limit * 2)
                if not is_noise(it["title"], it["url"], it.get("body") or it.get("summary") or "")
            ][:limit]
        except Exception as e:
            log.error("fallback failed: %s", e)
    return out
