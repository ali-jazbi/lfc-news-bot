"""منبع ۱: سایت رسمی باشگاه — https://www.liverpoolfc.com/news

روش: صفحه لیست را می‌گیرد، لینک خبرها را درمی‌آورد، سپس هر خبر را با
متاتگ‌های og: (عنوان/توضیح/عکس) + پاراگراف‌های متن استخراج می‌کند.
اگر ساختار سایت عوض شد، falling back to Google News RSS خودکار فعال می‌شود.
"""
import logging
import re
from urllib.parse import urljoin, unquote

import config
from sources.base import http_get, soup_of, meta, clean_text

log = logging.getLogger("src.lfc")
GOOGLE_FALLBACK = (
    "https://news.google.com/rss/search?q=site:liverpoolfc.com+when:1d&hl=en-GB&gl=GB&ceid=GB:en"
)

# این کلمات در آدرس عکس، یعنی لوگو/آیکون است نه عکس واقعی خبر
_IMG_SKIP = (
    "logo", "icon", "avatar", "sprite", "placeholder", "badge", "crest",
    "blank", "spacer", "pixel", "transparent", "1x1", "loading", "lazyload",
    "lazy-load", "skeleton",
)
MAX_ALBUM_IMAGES = 10


# فقط پسوندهای قابل نمایش در تلگرام — svg/gif/extensionless (عکس سفید/خراب در آلبوم) حذف می‌شود
_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


# عکس‌های واقعی محتوای خبر در Drupal سایت باشگاه فقط زیر این مسیر میزبانی می‌شوند.
# لوگو/آیکون/بنر اسپانسر (crest.webp, standard-chartered.webp, icon-*.webp) در ریشه سایت‌اند و رد می‌شوند.
_IMG_CONTENT_PATH = "/sites/default/files/"


def _img_key(u):
    """کلید یکتا‌سازی برای تشخیص عکس‌های تکراری.

    نام فایل بدون پسوند و بدون انکودینگ URL نگه داشته می‌شود چون همان عکس
    با پسوند متفاوت (.jpg در og:image در برابر .webp در بدنه)، هاست متفاوت،
    استایل متفاوت (styles/lg, md, ...) و توکن متفاوت (?itok=...) تکرار می‌آید.
    نام فایل در سایت باشگاه دارای هش یکتا است، پس معیار امنی برای تشخیص تکراری است.
    """
    path = u.split("?")[0].split("#")[0].rstrip("/")
    name = unquote(path.rsplit("/", 1)[-1]).lower()
    return name.rsplit(".", 1)[0] if "." in name else name


_TITLE_TAIL = re.compile(
    r"\s*[-–|]\s*(Liverpool FC(\.com)?|Liverpool Football Club|LiverpoolFC\.com)\s*$",
    re.IGNORECASE,
)

# جملات تبلیغاتی خود سایت که خبر واقعی نیست (دعوت به تماشای ویدئو در سایت/All Red Video)
_VIDEO_CTA = re.compile(
    r"\bwatch\b[^.]{0,90}\b(on demand|below|live on|join here)\b"
    r"|\bin the videos?\b[^.]{0,25}\bbelow\b"
    r"|\ball red video\b"
    r"|\bjoin here\b",
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
    """گالری عکس، ویدئو، کویز و تبلیغ و مشابه ارزش پست کردن ندارند."""
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


def _article_images(s, primary):
    """همه عکس‌های واقعی خبر (برای آلبوم/group photo) — لوگو، آیکون، placeholder خالی و تکراری حذف می‌شوند."""
    imgs = []
    seen = set()

    def _add(u):
        if not u:
            return False
        u = u.strip()
        if u.startswith("data:"):
            # base64/placeholder است — نه عکس واقعی، نه قابل ارسال به عنوان URL
            return False
        u = urljoin("https://www.liverpoolfc.com", u)
        low = u.lower()
        if any(x in low for x in _IMG_SKIP):
            return False
        path = low.split("?")[0].split("#")[0]
        if not path.endswith(_IMG_EXT):
            # svg، gif، placeholder بدون پسوند و... → در آلبوم سفید/خراب دیده می‌شوند
            return False
        if _IMG_CONTENT_PATH not in low:
            # لوگو، آیکون و بنر اسپانسر در ریشه سایت هستند — فقط فایل‌های محتوایی خبر قبول می‌شوند
            return False
        key = _img_key(u)
        if not key or key in seen:
            return False
        seen.add(key)
        imgs.append(u)
        return True

    _add(primary)

    container = (
        s.find("article")
        or s.find(attrs={"class": re.compile(r"article|content|body", re.I)})
        or s
    )
    for img in container.find_all("img"):
        if len(imgs) >= MAX_ALBUM_IMAGES:
            break
        # data-src/srcset اولویت دارند چون خیلی از سایت‌ها در src فقط یک تصویر خالی/blank برای lazy-load می‌گذارند
        candidates = [
            img.get("data-src"),
            img.get("data-srcset"),
            img.get("srcset"),
            img.get("src"),
        ]
        for c in candidates:
            if not c:
                continue
            if "," in c:
                # بزرگ‌ترین کاندیدا (آخرین آیتم srcset) را انتخاب کن
                c = c.split(",")[-1].strip().split(" ")[0]
            if _add(c):
                break
    return imgs


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
        if len(t) > 40 and "cookie" not in t.lower() and not _VIDEO_CTA.search(t):
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
        "images": _article_images(s, image),
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
                "images": [],
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
                log.info("rejected (%s): %s", why, art["title"][:60])
                continue
            out.append(art)
        except Exception as e:
            log.warning("article failed %s: %s", url, e)

    if not out:
        log.warning("direct site parse gave nothing — falling back to Google News")
        try:
            out = [
                it for it in _google_fallback(limit * 2)
                if not is_noise(it["title"], it["url"], it.get("body") or it.get("summary") or "")
            ][:limit]
        except Exception as e:
            log.error("fallback failed: %s", e)
    return out
