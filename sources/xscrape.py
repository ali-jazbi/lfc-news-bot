"""اسکرپ مستقیم x.com — جایگزین آینه‌های نیتر (حالت TWITTER_MODE=xscrape).

پورت از بات Liverpool-bot که ماه‌ها روی پروداکشن کار کرده: صفحه‌ی پروفایل
x.com از سمت سرور رندر می‌شود و داده‌ی توییت‌ها داخل یک <script> به شکل
relay records (کلیدهای base64 شده) جاسازی شده. همین‌جا متن، عکس و لینک
مستقیم mp4 ویدیو (با بالاترین bitrate) در آن هست — بدون API، بدون لاگین.

خروجی `scrape_user` عمداً همان قرارداد entry نیتر را دارد
({title, link, summary, image, published}) تا بقیه‌ی پایپ‌لاین
(فیلترها، _attach_media، فرمتر) بدون تغییر کار کند. دو کلید side-channel
هم اضافه می‌شود: `_xscrape_media` و `_xscrape_quoted`.

ریسک شناخته‌شده: اگر x.com فرمت relay را عوض کند یا IP دیتاسنتر را بلاک
کند، parser خالی برمی‌گرداند — twitter.fetch بعد از چند سیکل مرده به
نیتر fallback می‌کند (XSCRAPE_FALLBACK_CLASSIC).
"""
import base64
import email.utils
import logging
import re
import time

import requests

import config

log = logging.getLogger("src.xscrape")

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_session = requests.Session()


def fetch_page(screen_name, timeout=None):
    """HTML صفحه‌ی پروفایل؛ None روی هر خطایی — هیچ‌وقت raise نمی‌کند."""
    if timeout is None:
        timeout = getattr(config, "XSCRAPE_TIMEOUT", 20)
    try:
        r = _session.get(
            "https://x.com/%s" % screen_name,
            timeout=timeout,
            headers={"User-Agent": _UA},
        )
        if r.status_code == 200 and r.text:
            return r.text
        log.debug("x.com %s -> HTTP %s", screen_name, r.status_code)
    except Exception as e:
        log.debug("x.com %s failed: %s", screen_name, e)
    return None


def extract_relay_script(html):
    """اولین <script> که داده‌ی relay را دارد (شامل relayRecords+TBirdData)."""
    for m in re.finditer(r"<script[^>]*>", html):
        start = m.end()
        end_m = re.search(r"</script>", html[start:])
        if not end_m:
            continue
        script = html[start:start + end_m.start()]
        if ("relayRecords" in script and "TBirdData" in script
                and len(script) >= 10000):
            return script
    return None


def _read_balanced(script, obj_start):
    """از موقعیت `{` تا بسته‌شدن آکولاد متناظر — برش بلوک JSON-مانند."""
    depth = 1
    end = obj_start + 1
    while end < len(script) and depth > 0:
        if script[end] == '{':
            depth += 1
        elif script[end] == '}':
            depth -= 1
        end += 1
    return script[obj_start:end]


def extract_media(script, tid):
    """[{type: 'video'|'image', url}] برای توییت tid — mp4 با بیشترین bitrate."""
    raw_b64 = base64.b64encode(f'Tweet:{tid}'.encode()).decode()
    media_items = []
    media_idx = 0
    while True:
        search_key = f'client:{raw_b64}:media_entities2:{media_idx}":'
        det_pos2 = script.find(search_key)
        if det_pos2 == -1:
            break

        obj_start = script.find('{', det_pos2)
        if obj_start == -1:
            media_idx += 1
            continue

        ctx = script[det_pos2:det_pos2 + 200]
        if 'ApiMediaEntity' not in ctx:
            media_idx += 1
            continue

        block2 = _read_balanced(script, obj_start)
        type_m = re.search(r'type:"([^"]+)"', block2)
        url_m = re.search(r'media_url_https:"([^"]+)"', block2)

        mtype = type_m.group(1) if type_m else 'photo'
        murl = url_m.group(1) if url_m else None

        if murl:
            if mtype in ('video', 'animated_gif'):
                best_video = None
                var_idx = 0
                while True:
                    var_def = (f'client:{raw_b64}:media_entities2:'
                               f'{media_idx}:video_info:variants:{var_idx}":')
                    var_pos = script.find(var_def)
                    if var_pos == -1:
                        break
                    vo_start = script.find('{', var_pos)
                    if vo_start != -1:
                        vblock = _read_balanced(script, vo_start)
                        if 'video/mp4' in vblock:
                            vu_m = re.search(r'url:"([^"]+)"', vblock)
                            br_m = re.search(r'bitrate:(\d+)', vblock)
                            if vu_m:
                                bitrate = int(br_m.group(1)) if br_m else 0
                                if best_video is None or bitrate > best_video.get('bitrate', 0):
                                    best_video = {'url': vu_m.group(1), 'bitrate': bitrate}
                    var_idx += 1
                if best_video:
                    media_items.append({"type": "video", "url": best_video['url']})
                else:
                    media_items.append({"type": "image", "url": murl + "?format=jpg&name=large"})
            else:
                media_items.append({"type": "image", "url": murl + "?format=jpg&name=large"})

        media_idx += 1

    # حذف تکراری بر اساس URL
    seen = set()
    deduped = []
    for item in media_items:
        if item["url"] not in seen:
            seen.add(item["url"])
            deduped.append(item)
    return deduped


def extract_author(script, q_b64):
    """(display_name, screen_name) نویسنده‌ی یک توییت، یا (None, None)."""
    core_pos = script.find(f'client:{q_b64}:core":$R')
    if core_pos == -1:
        return None, None
    chunk = script[core_pos:core_pos + 300]
    m = re.search(r'(VXNlclJlc3VsdHM6[A-Za-z0-9+/=]+)', chunk)
    if not m:
        return None, None
    u_pos = script.find(f'{m.group(1)}":$R')
    if u_pos == -1:
        return None, None
    chunk2 = script[u_pos:u_pos + 300]
    m2 = re.search(r'(VXNlcjox[A-Za-z0-9+/=]+)', chunk2)
    if not m2:
        return None, None
    ucore_pos = script.find(f'client:{m2.group(1)}:core":$R')
    if ucore_pos == -1:
        return None, None
    chunk3 = script[ucore_pos:ucore_pos + 300]
    m3 = re.search(
        r'__typename:"UserCore",name:"((?:[^"\\]|\\.)*)",screen_name:"([^"]+)"',
        chunk3)
    if not m3:
        return None, None
    return m3.group(1), m3.group(2)


def extract_quoted_tweet(script, b64, tid):
    """اگر توییت نقل‌قول باشد، داده‌ی توییت نقل‌شده (یا None)."""
    ent_pos = script.find(f'"{b64}":$R[')
    if ent_pos == -1:
        return None
    brace_pos = script.find('{', ent_pos)
    if brace_pos == -1:
        return None
    entity = _read_balanced(script, brace_pos)
    qr_m = re.search(
        r'quoted_tweet_results:\$R\[\d+\]=\{__ref:"TweetResults:(\d+)"\}',
        entity)
    if not qr_m:
        return None

    qid = qr_m.group(1)
    q_b64 = base64.b64encode(f'Tweet:{qid}'.encode()).decode()

    q_text = ""
    qdet_pos = script.find(f'client:{q_b64}:details":$R[')
    if qdet_pos != -1:
        qd_brace = script.find('{', qdet_pos)
        if qd_brace != -1:
            qblock = _read_balanced(script, qd_brace)
            q_ft = re.search(r'full_text\s*:\s*"((?:[^"\\]|\\.)*)"', qblock)
            if q_ft:
                q_text = q_ft.group(1).replace('\\n', '\n')

    author_name, author_screen = extract_author(script, q_b64)
    return {
        "id": qid,
        "text": q_text,
        "media": extract_media(script, qid),
        "author_name": author_name,
        "author_screen_name": author_screen,
    }


def parse_relay_tweets(script, count):
    """توییت‌های صفحه → [{id, text, media, quoted}] مرتب بر اساس id نزولی."""
    pinned_ids = set()
    pm = re.search(r'pinned_entry_ids:\$R\[\d+\]=\[([^\]]*)\]', script)
    if pm:
        pinned_ids = set(re.findall(r'tweet-(\d+)', pm.group(1)))

    tweets = []
    idx = 0
    while True:
        det_pos = script.find(':details":$R[', idx)
        if det_pos == -1:
            break

        key_start = script.rfind('"', max(0, det_pos - 200), det_pos)
        if key_start == -1:
            idx = det_pos + 1
            continue

        key = script[key_start:det_pos + 13]
        b64_m = re.search(r'VHdlZXQ6([A-Za-z0-9+/=]+)', key)
        if not b64_m:
            idx = det_pos + 1
            continue

        b64 = b64_m.group(0)
        try:
            decoded = base64.b64decode(b64).decode()
            tid = decoded.split(':')[1]
        except Exception:
            idx = det_pos + 1
            continue

        if tid in pinned_ids:
            idx = det_pos + 1
            continue

        brace_pos = script.find('{', det_pos)
        if brace_pos == -1:
            idx = det_pos + 1
            continue

        block = _read_balanced(script, brace_pos)
        # در relay واقعی بعضی کلیدها quote دارند و بعضی ندارند — هر دو را بپذیر
        ca_m = re.search(r'created_at_ms"?\s*:\s*(\d+)', block)
        ft_m = re.search(r'full_text"?\s*:\s*"((?:[^"\\]|\\.)*)"', block)

        if not (ca_m and ft_m):
            idx = brace_pos + len(block)
            continue

        tweets.append({
            "id": tid,
            "created_at_ms": int(ca_m.group(1)),
            "text": ft_m.group(1).replace('\\n', '\n'),
            "media": extract_media(script, tid),
            "quoted": extract_quoted_tweet(script, b64, tid),
        })

        idx = brace_pos + len(block)
        if len(tweets) >= count:
            break

    tweets.sort(key=lambda t: int(t["id"]) if t["id"].isdigit() else 0,
                reverse=True)
    return tweets[:count]


def _ms_to_rfc822(ms):
    """millisecond توییتر → رشته‌ی RFC822 (قرارداد published نیتر)."""
    return email.utils.formatdate(ms / 1000.0, usegmt=True)


def scrape_user(screen_name, count=None):
    """entry های نیتر-سازگار برای یک حساب؛ [] روی هر خطا (هرگز raise نمی‌کند)."""
    if count is None:
        count = getattr(config, "XSCRAPE_TWEETS_PER_ACCOUNT", 8)
    try:
        html = fetch_page(screen_name)
        if not html:
            return []
        script = extract_relay_script(html)
        if not script:
            # صفحه آمد ولی داده‌ی relay نبود — احتمالاً بلاک/چالش JS
            log.debug("x.com %s: no relay data in page", screen_name)
            return []
        entries = []
        for t in parse_relay_tweets(script, count):
            link = "https://x.com/%s/status/%s" % (screen_name, t["id"])
            media = t.get("media") or []
            image = next((m["url"] for m in media if m["type"] == "image"),
                         None)
            quoted = t.get("quoted")
            entries.append({
                "title": (t["text"] or "")[:200],
                "link": link,
                "summary": t["text"] or "",
                "image": image,
                "published": _ms_to_rfc822(t.get("created_at_ms")
                                           or int(time.time() * 1000)),
                "_xscrape_media": media,
                "_xscrape_quoted": quoted,
            })
        return entries
    except Exception as e:
        log.debug("scrape_user %s failed: %s", screen_name, e)
        return []
