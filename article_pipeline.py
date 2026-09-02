"""Article pipeline: link → archive.today → scrape → translate → Telegraph → Instant View.

Fully async (aiohttp + asyncio). The sync bot calls run() from a worker thread —
asyncio.run() inside that thread isolates the event loop from main.py's threads.

Repeat links are cached in SQLite (articles table, keyed by normalized URL):
a repeat link returns the finished Telegraph link instantly, no re-processing.

archive.today is best-effort:
  1. First check if a snapshot ALREADY exists (archive.today/newest/<url>) —
     this needs no submit and no CAPTCHA, and paywalled pages (The Athletic etc.)
     are usually archived in full by someone else.
  2. Only if none exists, submit a new snapshot. reCAPTCHA on submit cannot and
     should not be automated — when it appears, the pipeline falls back to
     scraping the original site directly.
"""
from __future__ import annotations

import asyncio
import html as html_mod
import json
import logging
import re
import time
from urllib.parse import quote_plus, urljoin, urlparse, urlunparse

import aiohttp

import config
import db

log = logging.getLogger("article")

# Mirrors of the same service — first one that answers wins.
ARCHIVE_MIRRORS = ("https://archive.today", "https://archive.ph", "https://archive.is")
ARCHIVE_POLL_SECONDS = 75      # how long to wait for the snapshot to finish
ARCHIVE_POLL_INTERVAL = 4
TELEGRAPH_API = "https://api.telegra.ph"
MAX_BODY_CHARS = 60000         # hard cap before translation
MAX_TEXT_ITEMS = 600             # safety cap; not a short-article cap
MAX_TELEGRAPH_PARAS = 200
MIN_USABLE_BODY = 200          # thinner than this = extraction failed

_TIMEOUT = aiohttp.ClientTimeout(total=90)
_HEADERS = {"User-Agent": getattr(config, "USER_AGENT", "Mozilla/5.0"),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"}

_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|msclkid$|spm$|scid$|igshid$)", re.I)

_inflight: set[str] = set()
_telegraph_token: str | None = None


# ------------------------------------------------------------------ url utils
def normalize_url(url: str) -> str:
    """Canonical form for the dedup key: tracking params stripped, host lowercased."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urlparse(url)
    kept = [kv for kv in (p.query.split("&") if p.query else [])
            if kv and not _TRACKING_PARAMS.match(kv.split("=", 1)[0])]
    query = "&".join(kept)
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme or "https", host, path, "", query, ""))


def site_name(url: str) -> str:
    try:
        host = urlparse(url).netloc
        return re.sub(r"^www\.", "", host)
    except Exception:
        return url[:60]


def author_name() -> str:
    return getattr(config, "TELEGRAPH_AUTHOR_NAME", "") or "LIVERPOOL IRANI | لیورپول ایرانی"


# ------------------------------------------------------------------ http
def _arch_headers() -> dict:
    """هدرهای مخصوص archive.today — با کوکی سشن مرورگر خودت اگر در .env ست شده.

    کوکی را یک‌بار در مرورگر (بعد از رد کردن دستی security check) از DevTools
    کپی کن:  ARCHIVE_TODAY_COOKIE=...  →  از آن به بعد ربات همان سشن را دارد.
    """
    h = dict(_HEADERS)
    cookie = getattr(config, "ARCHIVE_TODAY_COOKIE", "")
    if cookie:
        h["Cookie"] = cookie
    return h


async def _get_text(session: aiohttp.ClientSession, url: str, headers: dict | None = None) -> str:
    """GET با تحمل 429 — archive.today و archive.org به IPهای اشتراکی سخت می‌گیرند."""
    hdrs = headers or _HEADERS
    last: Exception | None = None
    for attempt in range(3):
        try:
            async with session.get(url, headers=hdrs, allow_redirects=True) as r:
                if r.status == 200:
                    return (await r.read()).decode("utf-8", "replace")
                if r.status == 429:
                    try:
                        wait = int(r.headers.get("Retry-After") or 0)
                    except ValueError:
                        wait = 0
                    wait = min(wait or 5 * (attempt + 1), 30)
                    log.info("429 from %s — sleeping %ss (%s/3)",
                             urlparse(url).netloc, wait, attempt + 1)
                    last = RuntimeError("HTTP 429 (rate limited)")
                    await asyncio.sleep(wait)
                    continue
                raise RuntimeError(f"HTTP {r.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last = e
            await asyncio.sleep(3 * (attempt + 1))
    raise last or RuntimeError("fetch failed")


# ------------------------------------------------------------------ archive.today
_SNAPSHOT_TS_PATH = re.compile(r"^/(?:\d{4}\.\d{2}\.\d{2}-\d{6}|\d{14})/", re.I)  # /2026.09.01-023342/… یا /20260901023342/…
_SNAPSHOT_ID_PATH = re.compile(r"^/[0-9A-Za-z]{5,11}$")                    # /AAmjs
_CAPTCHA_MARKS = re.compile(r"recaptcha|are you a robot|verify you are|prove you are|security check", re.I)

# ویجت‌های «Cocoon AI Summary» سایت NYT/Athletic — کل بلوک باید از DOM حذف شود،
# نه فقط خط لیبلش. روی اسنپ‌شات‌های archive.today رندرشده دیده می‌شوند.
_AI_SUMMARY_WIDGET = re.compile(r"^\s*(\w+\s+)?ai summary\b", re.I)

# خطوط UI/ویجت که نباید وارد بدنه شوند (کپشن عکس، خلاصه‌ی AI سایت، دکمه‌ها و…)
_JUNK_TEXT = re.compile(
    r"^(photo|photos|ap photo|getty|afp|reuters photo|advertisement|ad |ai summary|"
    r"\w+ ai summary|summary generated|share this|sign up|subscribe|log in|sign in|"
    r"related|editor.s picks|most read|top stories|read more|skip to|follow us|"
    r"save|bookmark|copy link|whatsapp|twitter|x |facebook|email|print|reprints|"
    r"connections|spot the pattern|find the hidden link|wordle|crossword|"
    r"play now|games|gift this article|gift article)\b",
    re.I,
)
# خرده‌های ناوبری NYT که خطِ مستقل می‌شوند: «Transfer» ، «Window» ، «Transfer | Window».
# فقط وقتی خط همین‌هاست حذف می‌شود، نه جمله‌ای که با Transfer شروع می‌شود.
_NAV_CRUMB = re.compile(r"^(transfer|window|scores|standings|fixtures|tables)\s*(\||$)", re.I)
_JUNK_ELEMENTS = re.compile(
    r"caption|credit|advert|promo|newsletter|related|share|signup|breadcrumb|"
    r"comments|tags|article-footer|recirc|trending", re.I,
)
_IMAGE_JUNK_URL = re.compile(r"logo|icon|sprite|avatar|placeholder|1x1|pixel", re.I)


def _is_snapshot_url(u: str) -> bool:
    """True if the URL looks like a finished snapshot (timestamped or short-id form)."""
    path = urlparse(u).path
    return bool(_SNAPSHOT_TS_PATH.match(path) or _SNAPSHOT_ID_PATH.fullmatch(path))


async def _existing_snapshot(session: aiohttp.ClientSession, url: str) -> str | None:
    """Return an already-existing snapshot — no submit, no CAPTCHA, usually instant.

    This is the key for paywalled pages (The Athletic/NYT): other people have
    almost always archived them in full already, and viewing is open to all.
    Even a 429 is useful here: the redirect chain still reveals where the
    snapshot lives, and _get_text retries the content fetch with backoff.
    """
    headers = _arch_headers()
    for mirror in ARCHIVE_MIRRORS:
        try:
            async with session.get(f"{mirror}/newest/{url}", headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=25),
                                   allow_redirects=True) as r:
                final = str(r.url)
                # 200 = خواندنی؛ 429 = rate-limit ولی redirect مقصد اسنپ‌شات را لو می‌دهد
                if r.status not in (200, 429):
                    continue
                if "/newest" in final or "/submit" in final or not _is_snapshot_url(final):
                    continue
                return final
        except (aiohttp.ClientError, asyncio.TimeoutError):
            continue
    return None


async def _wayback_existing(session: aiohttp.ClientSession, url: str) -> str | None:
    """Captcha-free second source: Wayback Machine availability API."""
    try:
        async with session.get("https://archive.org/wayback/available", params={"url": url},
                               headers=_HEADERS,
                               timeout=aiohttp.ClientTimeout(total=25)) as r:
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
        snap = ((data or {}).get("archived_snapshots") or {}).get("closest") or {}
        if snap.get("available") and snap.get("url"):
            return snap["url"]
    except Exception as e:
        log.debug("wayback availability failed: %s", e)
    return None


def _wayback_raw(url: str) -> str:
    """https://web.archive.org/web/TS/URL → …/TSid_/URL (HTML خام، بدون تولبار)."""
    m = re.match(r"(https://web\.archive\.org/web/\d+)(?:id_)?/(.*)", url)
    return f"{m.group(1)}id_/{m.group(2)}" if m else url


async def archive_url(session: aiohttp.ClientSession, url: str) -> str | None:
    """Get a snapshot URL: existing one first, then a fresh submit.

    Returns the snapshot URL, or None on any failure — including CAPTCHA on
    submit (cannot/should not be automated; caller falls back to the original).
    """
    # 1) already archived? → done, zero CAPTCHA exposure
    existing = await _existing_snapshot(session, url)
    if existing:
        log.info("existing archive snapshot found: %s", existing[:100])
        return existing

    # 2) no snapshot yet → submit a new one (best-effort, mirror by mirror)
    try:
        headers = _arch_headers()
        for mirror in ARCHIVE_MIRRORS:
            try:
                # the submit form sets a session cookie first
                await session.get(f"{mirror}/submit/", params={"url": url}, headers=headers,
                                  timeout=aiohttp.ClientTimeout(total=25))
            except (aiohttp.ClientError, asyncio.TimeoutError):
                continue

            async with session.post(f"{mirror}/submit/",
                                    data={"url": url, "submit": "save"},
                                    headers=headers, allow_redirects=False,
                                    timeout=aiohttp.ClientTimeout(total=40)) as resp:
                loc = resp.headers.get("Location", "") if resp.status in (301, 302, 303, 307, 308) else ""
                head = (await resp.read())[:4000].decode("utf-8", "replace") if resp.status == 200 else ""

            if not loc:
                if _CAPTCHA_MARKS.search(head):
                    log.warning("archive.today served a CAPTCHA on submit — not automatable, "
                                "falling back to direct scrape")
                else:
                    log.info("archive submit at %s did not redirect — trying next mirror", mirror)
                continue

            m = re.search(r"/(?:wip/)?([0-9a-zA-Z]{5,})/?$", loc)
            if not m:
                continue
            snapshot = f"{mirror}/{m.group(1)}"

            deadline = time.monotonic() + ARCHIVE_POLL_SECONDS
            while time.monotonic() < deadline:
                await asyncio.sleep(ARCHIVE_POLL_INTERVAL)
                try:
                    async with session.get(snapshot, headers=headers, allow_redirects=True) as r:
                        # While pending, archive redirects to /wip/<id>; done → 200 at /<id>
                        if r.status == 200 and "/wip/" not in str(r.url):
                            return str(r.url)
                except aiohttp.ClientError:
                    pass
            log.info("archive snapshot %s did not complete in %ss", m.group(1), ARCHIVE_POLL_SECONDS)
            return None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("archive.today failed for %s: %s", url[:80], e)
    return None


# ------------------------------------------------------------------ extraction
def extract_article(html_text: str, base_url: str = "") -> dict:
    """Pull title / author / og:image / body text out of a page (archive copy or original).

    UI junk (photo credits, on-page AI summaries, share buttons, …) is filtered
    so it never leaks into the published page.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_text, "lxml")

    def meta(*names: str) -> str:
        for n in names:
            tag = (soup.find("meta", attrs={"property": n})
                   or soup.find("meta", attrs={"name": n}))
            if tag and (tag.get("content") or "").strip():
                return tag["content"].strip()
        return ""

    title = meta("og:title", "twitter:title")
    if not title and soup.h1:
        title = soup.h1.get_text(" ", strip=True)
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    author = meta("author", "og:author", "article:author", "twitter:creator")
    if not author:
        byline = soup.find(class_=re.compile(r"byline|author|article__author", re.I))
        if byline:
            author = byline.get_text(" ", strip=True)

    image = meta("og:image", "twitter:image")
    if image.startswith("//"):
        image = "https:" + image

    root = soup.find("article") or soup.find("main") or (soup.body or soup)
    for t in root(["script", "style", "nav", "header", "footer", "aside", "form",
                   "noscript", "iframe", "button", "svg"]):
        t.decompose()
    # ویجت‌های تزئینی را از DOM حذف کن (کپشن، اعتبار عکس، باکس اشتراک و…)
    for t in root.select("[class*=caption],[class*=credit],[class*=advert],[class*=promo],"
                         "[class*=newsletter],[class*=related],[class*=share],[class*=signup],"
                         "[id*=advert],[class*=breadcrumb],[class*=comments],[class*=recirc],"
                         "[class*=cocoon],[id*=cocoon],[class*=summary-widget],[id*=summary],"
                         "[id*=fides],[class*=fides],[id*=onetrust],[class*=consent],[id*=consent]"):
        t.decompose()
    # بلوک AI Summary با هر ساختاری: از متنِ لیبل («Cocoon AI Summary») به بالای
    # درخت می‌رویم و بزرگ‌ترین جدِ‌کوچک‌تر از ۲۵۰۰ کاراکتر را حذف می‌کنیم —
    # یعنی خودِ ویجت، نه ظرف مقاله. لیبل گاهی آخرِ بلوک می‌آید.
    _ai_labels = [el for el in root.find_all(True)
                  if el.name not in ("script", "style")
                  and len(el.get_text(" ", strip=True)) < 60
                  and _AI_SUMMARY_WIDGET.match(el.get_text(" ", strip=True))]
    for s in _ai_labels:
        el, target = s.parent, None
        while el is not None and el is not root:
            if len(el.get_text(" ", strip=True)) >= 2500:
                break
            target = el
            el = el.parent
        if target is not None and target.parent is not None:
            target.decompose()

    parts: list[str] = []
    images: dict[int, str] = {}          # شماره مارکر → URL تصویر میانه‌ی مقاله
    videos: dict[int, str] = {}          # شماره مارکر → URL ویدیو/پلیر
    img_idx = 0
    video_idx = 0
    header_src = re.sub(r"^https?://", "", image or "").rstrip("/")
    els = root.find_all(["h2", "h3", "p", "li", "figure", "img", "video", "iframe", "blockquote"])
    for el in els:
        if getattr(el, "decomposed", False):
            continue
        if el.name in ("video", "iframe", "blockquote"):
            # ویدیوهای جاسازی‌شده را حذف نکن: جای آن‌ها را در متن حفظ کن.
            src = el.get("src") or el.get("data-src") or ""
            if not src:
                child = el.find(["source", "iframe"])
                src = (child.get("src") or child.get("data-src") or child.get("srcset") or "") if child else ""
            label = el.get_text(" ", strip=True)
            if el.name == "blockquote" and not ("twitter" in str(el.get("class", [])).lower() or "video" in str(el.get("class", [])).lower()):
                continue
            if src.startswith("//"):
                src = "https:" + src
            if src and not src.startswith("data:"):
                videos[video_idx] = src if src.startswith(("http://", "https://")) else urljoin(base_url, src)
                parts.append(f"\n[VIDEO-{video_idx}]\n")
                video_idx += 1
            elif label and len(label) < 300:
                parts.append(f"\n{label}\n")
            el.decompose()
            continue
        if el.name in ("figure", "img"):
            # عکس میانه‌ی مقاله → مارکر [IMG-n] سر جای خودش + آدرسش در دیکشنری.
            # Athletic عکس‌ها را بدون <figure> و مستقیم بین پاراگراف‌ها می‌گذارد.
            img = el.find("img") if el.name == "figure" else el
            src = (img.get("src") or img.get("data-src") or "") if img else ""
            if not src or src.startswith("data:"):
                # lazy-load: اولین URL از srcset
                srcset = (img.get("srcset") or "") if img else ""
                src = srcset.split(",")[0].strip().split(" ")[0] if srcset else ""
            if src and not src.startswith("data:") and not _IMAGE_JUNK_URL.search(src):
                try:
                    w = int(str(img.get("width") or 0).rstrip("px"))
                except (ValueError, AttributeError):
                    w = 0
                if (not w or w >= 300) and re.sub(r"^https?://", "", src).rstrip("/") != header_src:
                    if src.startswith(("http://", "https://")) or base_url:
                        full = urljoin(base_url, src) if not src.startswith(("http://", "https://")) else src
                        images[img_idx] = full
                        parts.append(f"\n[IMG-{img_idx}]\n")
                        img_idx += 1
            if el.name == "figure":
                el.decompose()
            continue
        txt = el.get_text(" ", strip=True)
        if not txt or len(txt) < 2:
            continue
        # خرده‌های ناوبری و خطوط UI-مانند وارد بدنه نشوند
        if _NAV_CRUMB.match(txt):
            continue
        if len(txt) < 120 and _JUNK_TEXT.match(txt):
            continue
        if el.name in ("h2", "h3"):
            parts.append("\n\n" + txt)
        elif el.name == "li":
            parts.append("• " + txt)
        else:
            parts.append(txt)
    body = "\n".join(parts)
    # پاک‌سازی نهایی خط‌به‌خط: روی اسنپ‌شات‌ها لیبل ویجت‌ها گاهی تگ‌تکه است
    # («Cocoon <b>AI</b> Summary») و فیلتر DOM-level آنها را نمی‌گیرد —
    # اینجا هر خط کوتاهِ زباله از بدنه‌ی مونتاژشده حذف می‌شود.
    body = "\n".join(
        ln for ln in body.split("\n")
        if not (len(ln) < 120 and (_JUNK_TEXT.match(ln) or _AI_SUMMARY_WIDGET.match(ln)))
    )
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS].rsplit(" ", 1)[0] + " …"

    # عکس جایگزین: اگر og:image نبود، اولین تصویر بزرگ داخل مقاله
    if not image:
        for img in root.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src or src.startswith("data:") or _IMAGE_JUNK_URL.search(src):
                continue
            try:
                w = int(str(img.get("width") or 0).rstrip("px"))
            except ValueError:
                w = 0
            if w and w < 300:
                continue
            image = src
            break
    if image and base_url and not image.startswith(("http://", "https://")):
        image = urljoin(base_url, image)

    return {"title": html_mod.unescape(title or "")[:300],
            "author": html_mod.unescape(author or "")[:150],
            "image": image,
            "images": images,
            "videos": videos,
            "body": body}


def _usable(art: dict | None) -> bool:
    return bool(art and art.get("title") and len(art.get("body") or "") >= MIN_USABLE_BODY)


# ------------------------------------------------------------------ translation
async def _translate(item: dict) -> dict | None:
    """The existing translate.py chain is sync (litellm) — run it in a thread."""
    import translate  # lazy: keeps this module importable without litellm
    return await asyncio.to_thread(translate.translate, item)


# ------------------------------------------------------------------ telegraph
async def _get_telegraph_token(session: aiohttp.ClientSession) -> str:
    global _telegraph_token
    if _telegraph_token:
        return _telegraph_token
    tok = getattr(config, "TELEGRAPH_TOKEN", "")
    if tok:
        _telegraph_token = tok
        return tok
    # No token configured — create a one-off account so the feature works out of the box.
    async with session.get(f"{TELEGRAPH_API}/createAccount",
                           params={"short_name": "lfcbot", "author_name": author_name()}) as r:
        data = await r.json(content_type=None)
    if not data.get("ok"):
        raise RuntimeError("telegraph createAccount: " + str(data.get("error"))[:200])
    _telegraph_token = data["result"]["access_token"]
    log.warning("TELEGRAPH_TOKEN is not set — created a one-off account. "
                "Put this into .env to reuse it: TELEGRAPH_TOKEN=%s", _telegraph_token)
    return _telegraph_token


_IMG_MARKER = re.compile(r"^\[?\s*IMG[-_ ]?(\d+)\s*\]?$", re.I)
_VIDEO_MARKER = re.compile(r"^\[?\s*VIDEO[-_ ]?(\d+)\s*\]?$", re.I)


def _nodes(body: str, image: str, images: dict | None = None, videos: dict | None = None) -> list[dict]:
    nodes: list[dict] = []
    if image:
        nodes.append({"tag": "img", "attrs": {"src": image}})
    images = images or {}
    videos = videos or {}
    paras = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]
    for p in (paras or [body.strip()])[:MAX_TELEGRAPH_PARAS]:
        # مارکر تصویر (حتی اگر مدل کمی خرابش کرده باشد) → گره‌ی واقعی img
        m = _IMG_MARKER.match(p)
        vm = _VIDEO_MARKER.match(p)
        if vm and int(vm.group(1)) in videos:
            nodes.append({"tag": "p", "children": [f"🎬 ویدیو: {videos[int(vm.group(1))]} "]})
            continue
        if m and int(m.group(1)) in images:
            nodes.append({"tag": "img", "attrs": {"src": images[int(m.group(1))]}})
            continue
        # مارکری که وسط پاراگراف جا مانده → جدا کن تا عکس‌ها جا نیفتند
        if images or videos:
            chunks = re.split(r"(\[?\s*(?:IMG|VIDEO)[-_ ]?\d+\s*\]?)", p, flags=re.I)
            buf = ""
            for ch in chunks:
                m2 = _IMG_MARKER.match(ch.strip())
                vm2 = _VIDEO_MARKER.match(ch.strip())
                if vm2 and int(vm2.group(1)) in videos:
                    if buf.strip():
                        nodes.append({"tag": "p", "children": [buf.strip()[:4000]]})
                        buf = ""
                    nodes.append({"tag": "p", "children": [f"🎬 ویدیو: {videos[int(vm2.group(1))]} "]})
                elif m2 and int(m2.group(1)) in images:
                    if buf.strip():
                        nodes.append({"tag": "p", "children": [buf.strip()[:4000]]})
                        buf = ""
                    nodes.append({"tag": "img", "attrs": {"src": images[int(m2.group(1))]}})
                else:
                    buf += ch
            if buf.strip():
                nodes.append({"tag": "p", "children": [buf.strip()[:4000]]})
            continue
        nodes.append({"tag": "p", "children": [p[:4000]]})
    return nodes


async def publish_telegraph(session: aiohttp.ClientSession, title: str,
                            body: str, image: str, images: dict | None = None,
                            videos: dict | None = None) -> str:
    token = await _get_telegraph_token(session)
    form = {
        "access_token": token,
        "title": (title or "Article")[:256],
        "author_name": author_name(),
        # بدون لینک نویسنده — نام برند فقط متنی می‌ماند و به مقاله اصلی لینک نمی‌خورد
        "author_url": "",
        "content": json.dumps(_nodes(body, image, images, videos), ensure_ascii=False),
        "return_content": "false",
    }
    async with session.post(f"{TELEGRAPH_API}/createPage", data=form) as r:
        data = await r.json(content_type=None)
    if not data.get("ok"):
        raise RuntimeError("telegraph createPage: " + str(data.get("error"))[:200])
    return data["result"]["url"]


def instant_view(telegraph_url: str) -> str:
    """telegra.ph pages are Instant View-native; t.me/iv is only for external URLs."""
    rhash = getattr(config, "IV_HASH", "")
    if rhash:
        return f"https://t.me/iv?url={quote_plus(telegraph_url)}&rhash={rhash}"
    return telegraph_url


# ------------------------------------------------------------------ messaging
def build_message(tr: dict, telegraph_url: str, archive: str = "", cached: bool = False) -> str:
    """پست تلگرام: تیتر + گزیده‌ای از خلاصه + لینک مشاهده‌ی کامل (صفحه Telegraph).

    لینک مقاله اصلی و آرشیو عمداً حذف شده‌اند — خواننده فقط به Telegraph می‌رود.
    """
    body = (tr.get("body") or "").strip()
    body = re.sub(r"\[?\s*IMG[-_ ]?\d+\s*\]?", " ", body)   # مارکر عکس در پیش‌نمایش نمی‌آید
    body = re.sub(r"[ \t]{2,}", " ", body).strip()
    if len(body) > 500:
        body = body[:500].rsplit(" ", 1)[0] + " …"
    parts = [f"📰 <b>{html_mod.escape((tr.get('title') or 'Article').strip())}</b>", "",
             html_mod.escape(body), ""]
    parts.append(f"⬇️ <a href=\"{html_mod.escape(telegraph_url)}\">مشاهده متن کامل مقاله</a>")
    if cached:
        parts.append("♻️ از حافظه")
    return "\n".join(parts)


# ------------------------------------------------------------------ orchestrator
async def process_article(url: str, force: bool = False) -> dict:
    norm = normalize_url(url)

    if not force:
        cached = db.article_get(norm)
        if cached and cached.get("status") == "done" and cached.get("telegraph_url"):
            tr = {"title": cached.get("title") or "Article", "body": ""}
            return {"ok": True, "cached": True,
                    "telegraph_url": cached["telegraph_url"],
                    "archive_url": cached.get("archive_url") or "",
                    "message": build_message(tr, cached["telegraph_url"],
                                             cached.get("archive_url") or "", cached=True)}
    if norm in _inflight:
        return {"ok": False, "error": "this link is already being processed"}
    _inflight.add(norm)
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            # 1) archive.today: existing snapshot → fresh submit (best-effort)
            archive = await archive_url(session, norm)

            # 2) captcha-free second chance: Wayback Machine
            if not archive:
                archive = await _wayback_existing(session, norm)
                if archive:
                    log.info("wayback snapshot found: %s", archive[:100])

            # 3) content: archive copy first, original as fallback (thin scrape or no archive)
            art, art_source = None, None
            if archive:
                try:
                    fetch_url = _wayback_raw(archive) if "web.archive.org" in archive else archive
                    snap_headers = _arch_headers() if "archive." in urlparse(archive).netloc else None
                    art = extract_article(await _get_text(session, fetch_url, snap_headers), fetch_url)
                    art_source = archive
                except Exception as e:
                    log.info("archive scrape failed (%s) — falling back to the original", e)
            if not _usable(art):
                art = extract_article(await _get_text(session, norm), norm)
                art_source = norm
            if not _usable(art):
                raise RuntimeError("failed to extract title/body — the page may be paywalled, "
                                   "and its archive copy is CAPTCHA-gated for this IP. "
                                   "Tip: set ARCHIVE_TODAY_COOKIE in .env (see module docstring).")

            # 3) translation via the existing chain (sync litellm → thread)
            tr = await _translate({"title": art["title"], "body": art["body"],
                                   "source": "article", "source_tag": site_name(norm)})
            if not tr or not (tr.get("body") or "").strip():
                raise RuntimeError("translation failed")

            # 4) Telegraph — بدون لینک نویسنده؛ فقط نام برند می‌آید؛
            #    عکس‌های میانه از روی مارکرهای [IMG-n] سر جایشان می‌نشینند
            turl = await publish_telegraph(session, tr.get("title") or art["title"],
                                           tr.get("body") or art["body"], art["image"],
                                           art.get("images") or {}, art.get("videos") or {})

        iv = instant_view(turl)
        db.article_save(norm, norm, archive or "", turl, tr.get("title") or art["title"])
        log.info("article done: %s → %s (archive=%s, source=%s)",
                 norm[:60], turl, bool(archive), art_source)
        return {"ok": True, "cached": False, "telegraph_url": turl, "iv_url": iv,
                "archive_url": archive or "", "message": build_message(tr, turl, archive or "")}
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("article pipeline failed for %s: %s", norm[:80], e)
        return {"ok": False, "error": str(e)[:300]}
    finally:
        _inflight.discard(norm)


def run(url: str, force: bool = False) -> dict:
    """Sync bridge for the thread-based bot: blocking call, own event loop."""
    return asyncio.run(process_article(url, force=force))


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
    if len(sys.argv) < 2:
        print("usage: python article_pipeline.py <url>")
        raise SystemExit(1)
    res = asyncio.run(process_article(sys.argv[1]))
    print(res.get("message") or ("ERROR: " + res.get("error", "unknown")))
