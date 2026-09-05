"""ساخت قالب پست تلگرام مطابق تمپلیت کانال."""
import html
import re

import config


def esc(t):
    return html.escape(t or "", quote=False)


def plain(html_text):
    """متن خالص HTML — تگ‌ها حذف و entity ها باز می‌شوند."""
    return html.unescape(_TAG_RE.sub("", html_text or "")).strip()


def _combined_source_label(item):
    """برچسب منبع کانال: اگر چند منبع وجود دارد، آن‌ها را با & ترکیب می‌کند."""
    source_tag = item.get("source_tag") or "Liverpool FC"
    extra = item.get("original_sources") or []
    if not extra:
        return source_tag

    names = []
    seen = set()
    for s in [source_tag] + [config.display_name(v.lstrip('@')) for v in extra if v]:
        key = (s or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(s)
    if len(names) <= 1:
        return source_tag
    return " & ".join(names[:2])


# ---------------------------------------------------------------- قواعد پست
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\u2600-\u27BF"
    "\u2B00-\u2BFF"
    "\uFE0F"
    "]+"
)
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

# خط آماری: با یک یا چند ایموجی شروع می‌شود و بلافاصله عدد دارد (لاتین یا فارسی)
_STATS_LINE = re.compile(
    r"^[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200d]{1,3}\s*"
    r"([\d\u06F0-\u06F9][^\n]{0,100})$"
)
_STAT_HINTS = (
    "پاس", "دفع", "دریبل", "نبرد", "شوت", "سیو", "مهار", "قطع", "دوئل",
    "سانتر", "تکل", "خطا", "گل", "موقعیت", "دقیقه", "لمس", "درصد", "تعویض",
    "pass", "dribble", "tackle", "save", "aerial", "duel", "shot", "touch",
    "key", "clearance", "interception", "accuracy", "minutes", "cross",
)

_SAY_VERB = re.compile(r"(گفت|نوشت|افزود|تأکید کرد|اظهار کرد|واکنش|پاسخ داد|می‌گوید|گفته)")
_QUOTE_SPAN = re.compile(r"«[^»]{20,}»")

_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")

_INTERVIEW_MARKERS = (
    "مصاحبه", "به نقل از", "گفت‌وگو", "گفتگو", "واکنش", "اظهارات",
    "اظهار کرد", "interview", "exclusive",
)


def _normalized(text):
    """متن بدون ایموجی/تگ HTML/علامت/فاصله — برای مقایسه عنوان و بدنه."""
    t = _TAG_RE.sub("", text or "")
    t = _EMOJI_RE.sub("", t)
    return re.sub(r"[\s\u200c]+", "", t).lower()


def _normalize_stats_emojis(body):
    """خط‌های آماری فقط با 🔹 شروع می‌شوند و ارقامشان فارسی می‌شود؛
    خطوط غیرآماری دست نمی‌خورند."""
    out = []
    for line in (body or "").split("\n"):
        m = _STATS_LINE.match(line.strip())
        if m and any(h in line.lower() for h in _STAT_HINTS):
            line = "\U0001F539 " + m.group(1).strip().translate(_FA_DIGITS)
        out.append(line)
    return "\n".join(out)


def _is_interview(item, tr):
    """تشخیص مصاحبه/نقل‌قول برای آیکون 🎙 به‌جای دایره."""
    text = " ".join([
        str(tr.get("title") or ""), str(tr.get("body") or "")[:400],
        str(item.get("title") or ""), str(item.get("body") or "")[:300],
    ]).lower()
    if any(m in text for m in _INTERVIEW_MARKERS):
        return True
    if item.get("_is_quote") and _QUOTE_SPAN.search(str(tr.get("body") or "")):
        return True
    return False


def _detect_quote_post(tr, body):
    """اگر پست دقیقاً یک نقل‌قول تکی داشته باشد (title, body_html) برمی‌گرداند
    تا جمله داخل بلاک‌کووت تلگرام برود. گوینده از قبل/بعد کووت بیرون کشیده
    و به عنوان چسبانده می‌شود تا دوبله نشود."""
    spans = _QUOTE_SPAN.findall(body)
    if len(spans) != 1:
        return None
    m = _QUOTE_SPAN.search(body)
    title = (tr.get("title") or "").strip()
    pre_raw = body[: m.start()].strip()
    post = body[m.end():].strip()
    pre = pre_raw.rstrip(":.،, ")
    speaker, drop_pre = "", False
    if (pre and len(pre) <= 60 and "\n" not in pre and "«" not in pre
            and (pre_raw.endswith((":", "،", ",")) or _SAY_VERB.search(pre))):
        speaker, drop_pre = pre, True
    else:
        am = re.match(r"(.{2,40}?)\s+(?:گفت|نوشت|اظهار کرد|تأکید کرد)\b", post)
        if am:
            speaker = am.group(1).strip()
    quote_text = m.group(0)
    # بعضی مدل‌ها عنوان را با خودِ نقل‌قول پر می‌کنند؛ چون نقل‌قول در بدنه
    # دوباره داخل blockquote می‌آید، آن بخش را از عنوان حذف می‌کنیم.
    if _normalized(quote_text) and _normalized(quote_text) in _normalized(title):
        title = re.sub(re.escape(quote_text), "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*[:：،—-]\s*$", "", title).strip()
    if speaker and speaker.lower() not in title.lower():
        title = f"{title} — {speaker}" if title else speaker
    pieces = []
    if pre_raw and not drop_pre:
        pieces.append(pre_raw)
    pieces.append(quote_text)
    if post:
        pieces.append(post)
    return (title, "\n".join(pieces))


def build_caption(item, tr):
    """نسخه نهایی و تمیز پست — دقیقاً همانی که روی کانال می‌رود.

    اگر خبر با /edit ادمین ویرایش شده باشد، فرمت HTML خودِ ادمین عیناً حفظ
    می‌شود (بولد، ایتالیک، لینک و...) — چون ذخیره‌شده escape مطمئن است.
    خروجی LLM همیشه escape می‌شود."""
    if tr.get("edited_html") and (tr.get("edited_body_html") or tr.get("edited_title_html")):
        body = _normalize_stats_emojis((tr.get("edited_body_html") or tr.get("body") or "").strip())
        title = (tr.get("edited_title_html") or tr.get("title") or "").strip()
    else:
        body = _normalize_stats_emojis(esc(tr.get("body", "")).strip())
        title = esc(tr.get("title", "")).strip()

    bullet = "\U0001F399" if _is_interview(item, tr) else (
        "\U0001F534" if tr.get("importance") == "high" else "\u26AA\uFE0F"
    )
    # اگر ادمین عنوانش را خودش با ایموجی شروع کرده، گلوله تکراری نمی‌گذاریم
    if tr.get("edited_title_html") and _EMOJI_RE.match((tr.get("edited_title_html") or "").lstrip()):
        bullet = ""

    # پست نقل‌قول/واکنش: جمله کووت‌شده در بلاک‌کووت تلگرام.
    # اگر ادمین با /edit متن را عوض کرده، دست نمی‌زنیم — متن او نهایی است
    # و هیچ بازسازی/جابه‌جایی قدیمی نباید داخلش نشت کند.
    quote = None if tr.get("edited_html") else _detect_quote_post(tr, body)
    if quote:
        q_title, q_body = quote
        head = f"{bullet} <b>{q_title}</b>" if q_title else bullet
        parts = [head, "", f"<blockquote expandable>{q_body}</blockquote>", ""]
        parts.append(f"[{esc(_combined_source_label(item))}]")
        parts.append(config.CHANNEL_USERNAME)
        return "\n".join(parts)

    # عنوان باید حتی برای پست کوتاه نمایش داده شود؛ فقط وقتی عنوان و بدنه
    # واقعاً یکسان‌اند، یکی را حذف می‌کنیم تا متن دوبار تکرار نشود.
    # صرفاً «بخشی از بدنه بودن» کافی نیست: عنوان مستقلِ یک پست کوتاه نباید حذف شود.
    ntitle, nbody = _normalized(title), _normalized(body)
    is_duplicate_title = bool(ntitle and ntitle == nbody)

    title_html = f"<b>{title}</b>" if not tr.get("edited_title_html") else title
    if is_duplicate_title or not title:
        parts = [f"{bullet} {body}", ""]
    else:
        parts = [f"{bullet} {title_html}", "", body, ""]

    parts.append(f"[{esc(_combined_source_label(item))}]")
    parts.append(config.CHANNEL_USERNAME)
    return "\n".join(parts)


def build_original_source_note(item):
    """یادداشت منبع اصلی وقتی توییت نقل‌قول یا ریتوییت باشد.

    مثال‌ها:
      • «نقل‌قول از: @FabrizioRomano»
      • «بازنشر از: Sky Sport Austria»
    این متن فقط در پیش‌نمایش ادمین نشان داده می‌شود، روی کانال نمی‌رود.
    """
    orig = item.get("original_source")
    if not orig:
        return None
    orig_tag = item.get("original_source_tag") or orig
    # تشخیص نوع: اگر blockquote بوده باشد یعنی ریتوییت
    if item.get("_is_quote"):
        head = f"\U0001F4AC نقل‌قول از: {esc(orig_tag)} ({esc(orig)})"
    else:
        head = f"\U0001F517 منبع اصلی: {esc(orig_tag)} ({esc(orig)})"
    # منابع اضافه (هر @منشن دیگر در همان توییت) — فقط یادداشت ادمین
    extra = item.get("original_sources") or []
    extra = [s for s in extra if s.lower() != str(orig).lower()]
    if extra:
        tags = [f"{esc(config.display_name(s.lstrip('@')))} ({esc(s)})" for s in extra[:3]]
        head += "\n\U0001F465 منابع دیگر: " + "، ".join(tags)
    return head


def build_admin_caption(item, tr):
    """نسخه پیش‌نمایش در گروه ادمین‌ها (با لینک منبع و اطلاعات فنی)."""
    caption = build_caption(item, tr)
    src = item.get("url", "")
    tail = f"\n\n\u2500\u2500\u2500\n\U0001F517 <a href=\"{esc(src)}\">منبع اصلی</a>"
    if tr.get("provider"):
        tail += f" | ترجمه: {esc(str(tr['provider']))}"
    if tr.get("machine"):
        tail += "\n\u26A0\uFE0F ترجمه ماشینی — قبل از انتشار متن را بازبینی کن"
    # یادداشت منبع اصلی (نقل‌قول/ریتوییت)
    orig_note = build_original_source_note(item)
    if orig_note:
        tail += "\n\n" + orig_note
    return caption + tail


def build_original_message(item, expandable=True):
    """متن  دست‌نخورده — فقط برای چشم ادمین، روی کانال نمی‌رود.

    در بلاک‌کووت تاشو گذاشته می‌شود تا گروه را شلوغ نکند؛
    ادمین رویش بزند باز می‌شود.
    اگر منبع اصلی متفاوت باشد (نقل‌قول/ریتوییت)، اضافه می‌شود.
    """
    title = (item.get("title") or "").strip()
    body = (item.get("body") or "").strip()

    raw = title
    if body and body != title:
        # در توییت‌ها title فقط ۲۰۰ کاراکتر اول همان body است — دوباره نمی‌نویسیم
        head = title[:60].strip()
        if head and body.strip().startswith(head):
            raw = body
        else:
            raw = (raw + "\n\n" + body) if raw else body
    if not raw:
        return None

    # سقف پیام تلگرام ۴۰۹۶ کاراکتر است؛ با حاشیه امن می‌بریم
    if len(raw) > 3200:
        raw = raw[:3200].rsplit(" ", 1)[0] + " …"

    # یادداشت منبع اصلی (اگر نقل‌قول/ریتوییت باشد)
    orig_note = build_original_source_note(item)
    if orig_note:
        raw += "\n\n" + orig_note.replace("<", "&lt;").replace(">", "&gt;")

    head = "\U0001F4C4 <b>متن اصلی</b>\n"
    if expandable:
        return head + "<blockquote expandable>" + esc(raw) + "</blockquote>"
    return head + esc(raw)


def keyboard(key, mode="manual"):
    """دکمه‌ها — رفتار ثابت در هر دو حالت manual/auto:
    1. ترجمه مجدد      → rtr
    2. نسخه آماده انتشار → pub (نسخه تمیز در گروه ادمین)
    3. انتشار در کانال   → s2c (مستقیم روی کانال)
    4. متن اصلی         → orig (متن ، به‌جای پیام جداگانه)

    ویرایش دیگر دکمه ندارد: روی پیش‌نمایش ریپلای کن و /edit بزن."""
    return {
        "inline_keyboard": [
            [{"text": "\U0001F504 ترجمه مجدد", "callback_data": f"rtr:{key}"}],
            [{"text": "\U0001F4E4 نسخه آماده انتشار", "callback_data": f"pub:{key}"},
             {"text": "\U0001F4E2 انتشار در کانال", "callback_data": f"s2c:{key}"}],
            [{"text": "\U0001F4C4 متن اصلی", "callback_data": f"orig:{key}"}],
        ]
    }
