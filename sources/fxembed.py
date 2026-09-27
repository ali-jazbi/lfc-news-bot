"""منبع FxEmbed / FxTwitter API v2 — توییت‌های X بدون لاگین و بدون کلید.

چرا این ماژول ساخته شد: از اواسط سپتامبر ۲۰۲۶ صفحه‌ی پروفایل x.com دیگر
داده‌ی توییت‌ها را در HTML اولیه جاسازی نمی‌کند (نه `relayRecords` و نه
`TBirdData`)، پس پارسر `sources/xscrape.py` همیشه خالی برمی‌گرداند. صفحه
فقط یک shell است و داده از طریق API داخلی X (GraphQL) می‌آید که خودش نیاز
به کوکی/توکن دارد.

`api.fxtwitter.com` همان API عمومی‌ای است که سرویس embed از آن استفاده
می‌کند: رایگان، بدون API key، بدون Cookie، بدون لاگین. مستندات و OpenAPI:
    https://docs.fxembed.com/api/introduction/
    https://api.fxtwitter.com/2/openapi.json
سقف نرخ: ۱۰۰۰ درخواست در دقیقه برای هر IP (بیش از نیاز این بات).

خروجی `scrape_user` عیناً همان قرارداد entry نیتر/xscrape است
({title, link, summary, image, published} به‌علاوه‌ی دو side-channel
`_xscrape_media` و `_xscrape_quoted`) تا بقیه‌ی پایپ‌لاین — فیلترها،
`_attach_media`، فرمتر و تلگرام — دست نخورد.

دو نکته‌ی عملیاتی که با تست واقعی روی ۲۹ حساب پروژه کشف شد:
  ۱) این شبکه گاهی اتصال را نیمه‌کاره می‌بندد (RemoteDisconnected/SSLError)
     حتی وقتی API سالم است → هر درخواست چند تلاش دارد و هرگز raise نمی‌کند.
  ۲) برخی حساب‌ها در timeline پیش‌فرض ۴۰۴ می‌دهند (توییت اصلی ندارند) در
     حالی که پروفایلشان سالم است → یک بار با `with_replies=1` دوباره خوانده
     می‌شوند و نتیجه به توییت‌های خودِ همان حساب محدود می‌شود.
"""
import email.utils
import logging
import re
import time

import requests

import config

log = logging.getLogger("src.fxembed")

_UA = getattr(config, "USER_AGENT", "Mozilla/5.0")


def _cfg(name, default):
    return getattr(config, name, default)


def _base():
    return (getattr(config, "FXEMBED_BASE", "https://api.fxtwitter.com")
            or "https://api.fxtwitter.com").rstrip("/")


def _api_get(path, params=None):
    """GET روی API — خروجی (http_status, payload, error)؛ هرگز raise نمی‌کند.

    204 یعنی «هیچ پست تازه‌تری از زمان since نیست» → payload None است.
    """
    tries = max(1, _cfg("FXEMBED_FETCH_TRIES", 3))
    timeout = _cfg("FXEMBED_TIMEOUT", 20)
    url = _base() + path
    err = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params or {}, timeout=timeout,
                             headers={"User-Agent": _UA})
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            log.debug("fxembed %s try %d/%d failed: %s", path, i + 1, tries, err)
            if i < tries - 1:
                time.sleep(0.8 * (i + 1))
            continue
        if r.status_code == 204:
            return 204, None, None
        try:
            return r.status_code, r.json(), None
        except Exception as e:
            err = "bad-json: %s" % e
            log.debug("fxembed %s bad json: %s", path, err)
            if i < tries - 1:
                time.sleep(0.8 * (i + 1))
    return None, None, err


def _statuses_page(handle, count, since=None, cursor=None, with_replies=False):
    """یک صفحه‌ی timeline — dict با ok/http/code/message/results/cursor."""
    params = {"count": int(count)}
    if since:
        params["since"] = int(since)
    if cursor:
        params["cursor"] = cursor
    if with_replies:
        params["with_replies"] = "1"
    http, payload, err = _api_get("/2/profile/%s/statuses" % handle, params)
    page = {"ok": False, "http": http, "code": None, "message": err,
            "results": [], "cursor": None}
    if http == 204:
        page.update({"ok": True, "code": 204, "message": "nothing new"})
        return page
    if http != 200 or not isinstance(payload, dict):
        if http is not None:
            page["code"] = payload.get("code") if isinstance(payload, dict) else http
            page["message"] = (payload or {}).get("message") if isinstance(payload, dict) else err
        return page
    page.update({
        "ok": True,
        "code": payload.get("code"),
        "message": payload.get("message"),
        "results": payload.get("results") or [],
        "cursor": (payload.get("cursor") or {}).get("bottom"),
    })
    return page
def _status_from_result(result):
    """از یک آیتم results، خودِ status را بیرون می‌کشد (thread → status کانونی)."""
    if not isinstance(result, dict):
        return None
    if result.get("type") == "thread":
        st = result.get("status")
        return st if isinstance(st, dict) and st.get("id") else None
    if result.get("type") in (None, "status"):
        return result if result.get("id") else None
    return None          # tombstone / نوع ناشناخته


def _screen_name(node):
    """screen_name از dict یا str (API هر دو شکل را دارد)."""
    if isinstance(node, dict):
        return node.get("screen_name") or ""
    return node or ""


def _own_statuses(handle, results, allow_replies=True):
    """فقط توییت‌های خودِ حساب.

    در حالت پیش‌فرض API این فیلتر بی‌اثر است، ولی با `with_replies=1` تایم‌لاین
    «گفتگو» می‌شود و توییت دیگران هم می‌آید؛ آنجا فقط توییت/ریتوییت خودِ حساب
    می‌ماند و ریپلای‌ها (که خبر نیستند) حذف می‌شوند.
    """
    h = (handle or "").lower()
    out = []
    for r in results or []:
        st = _status_from_result(r)
        if not st:
            continue
        author = _screen_name(st.get("author")).lower()
        reposter = _screen_name(st.get("reposted_by")).lower()
        if author != h and reposter != h:
            continue
        if not allow_replies:
            replied = _screen_name(st.get("replying_to")).lower()
            if replied and replied != h:
                continue
        out.append(st)
    return out


def _best_mp4(item):
    """بهترین لینک mp4 یک مدیای ویدیویی (بدون وابستگی به m3u8)."""
    url = (item.get("url") or "").strip()
    if re.search(r"\.mp4(\?|$)", url, re.I):
        return url
    best, best_br = None, -1
    for fmt in item.get("formats") or []:
        if not isinstance(fmt, dict):
            continue
        fu = fmt.get("url") or ""
        is_mp4 = (fmt.get("container") or "").lower() == "mp4" \
            or re.search(r"\.mp4(\?|$)", fu, re.I)
        if not is_mp4:
            continue
        br = fmt.get("bitrate") or 0
        if br > best_br:
            best, best_br = fu, br
    return best


def _map_media(media):
    """media در FxTwitter → [{type: 'image'|'video', url}] مثل relay xscrape."""
    out, seen = [], set()
    if not isinstance(media, dict):
        return out
    items = media.get("all") or ((media.get("photos") or [])
                                 + (media.get("videos") or []))
    for m in items:
        if not isinstance(m, dict):
            continue
        kind = (m.get("type") or "").lower()
        if kind in ("video", "gif", "animated_gif"):
            mp4 = _best_mp4(m)
            url, mtype = mp4, "video"
            if not mp4:
                url, mtype = m.get("thumbnail_url") or m.get("url"), "image"
        else:
            url, mtype = m.get("url"), "image"
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"type": mtype, "url": url})
    return out


def _map_quote(quote):
    """quote → همان کلیدهایی که build_tweet_item انتظار دارد، یا None."""
    if not isinstance(quote, dict) or not quote.get("id"):
        return None
    author = quote.get("author") or {}
    return {
        "id": quote.get("id"),
        "link": quote.get("url"),
        "text": quote.get("text") or "",
        "author_screen_name": author.get("screen_name") or "",
        "author_name": author.get("name") or "",
        "media": _map_media(quote.get("media")),
    }


def _to_entry(status, handle):
    """status در FxTwitter → entry با قرارداد نیتر/xscrape."""
    text = (status.get("text") or "").strip()
    media = _map_media(status.get("media"))
    image = next((m["url"] for m in media if m["type"] == "image"), None)
    link = status.get("url") or ("https://x.com/%s/status/%s"
                                 % (handle, status.get("id")))
    published = ""
    try:
        published = email.utils.formatdate(float(status.get("created_timestamp")),
                                          usegmt=True)
    except Exception:
        published = ""
    return {
        "title": text[:200],
        "link": link,
        "summary": text,
        "image": image,
        "published": published,
        "_xscrape_media": media,
        "_xscrape_quoted": _map_quote(status.get("quote")),
    }


def scrape_user(screen_name, count=None, since=None):
    """entry های نیتر-سازگار برای یک حساب؛ [] روی هر خطا (هرگز raise نمی‌کند).

    `since` (Unix time) برای polling افزایشی است: اگر هیچ پست تازه‌تری نباشد
    API کد 204 می‌دهد و ما [] برمی‌گردانیم.
    """
    handle = (screen_name or "").lstrip("@").strip()
    if not handle:
        return []
    if count is None:
        count = _cfg("FXEMBED_TWEETS_PER_ACCOUNT", 20)

    page = _statuses_page(handle, count, since=since)
    if not page["ok"]:
        log.debug("fxembed @%s: timeline failed (http=%s code=%s %s)",
                  handle, page["http"], page["code"], page["message"])
    statuses = _own_statuses(handle, page["results"], allow_replies=True)

    # timeline پیش‌فرض خالی بود ولی حساب سالم است (تست واقعی: LiverpoolFF)
    # → یک بار با with_replies می‌خوانیم و به توییت‌های خودش محدود می‌کنیم.
    if not statuses and page["code"] == 404 and _cfg("FXEMBED_WITH_REPLIES_FALLBACK", True):
        page2 = _statuses_page(handle, count, since=since, with_replies=True)
        if page2["ok"]:
            statuses = _own_statuses(handle, page2["results"], allow_replies=False)
            # با since، خالی‌بودن معمولاً یعنی «حساب ساکن است» نه «توییت اصلی ندارد»
            (log.debug if since else log.info)(
                "fxembed @%s: default timeline empty → with_replies (%d)",
                handle, len(statuses))

    entries = [_to_entry(st, handle) for st in statuses[:count]]
    return entries


def _parse_tweet_url(url):
    """(handle, tweet_id) از لینک x.com/twitter.com، وگرنه (None, None)."""
    m = re.match(
        r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/(\w{1,15})"
        r"/status(?:es)?/(\d+)", (url or "").strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


def fetch_tweet(url):
    """یک توییت از لینکش (لینک خام ادمین) — (handle, entry) یا (None, None).

    endpoint: GET /2/status/{id} — همان قرارداد entry، پس `item_from_url` و
    فرمتر بدون تغییر کار می‌کنند. هرگز raise نمی‌کند.
    """
    handle, tid = _parse_tweet_url(url)
    if not tid:
        return None, None
    http, payload, err = _api_get("/2/status/%s" % tid)
    if http != 200 or not isinstance(payload, dict):
        log.info("fxembed tweet %s not available (http=%s %s)", tid, http, err)
        return None, None
    status = payload.get("status") or {}
    if not isinstance(status, dict) or status.get("id") != tid:
        # tombstone (توییت حذف‌شده/محدود) یا بدنه‌ی نامنتظر
        log.info("fxembed tweet %s returned no status (type=%s)",
                 tid, status.get("type"))
        return None, None
    author = _screen_name(status.get("author")) or handle
    return author, _to_entry(status, author)