"""ساخت قالب پست تلگرام مطابق تمپلیت کانال."""
import html

import config


def esc(t):
    return html.escape(t or "", quote=False)


def build_caption(item, tr):
    """نسخه نهایی و تمیز پست — دقیقاً همانی که روی کانال می‌رود."""
    bullet = "\U0001F534" if tr.get("importance") == "high" else "\u26AA\uFE0F"
    body = esc(tr.get("body", "")).strip()
    title = esc(tr.get("title", "")).strip()

    # تشخیص پست‌های کوتاه/تک‌خطی: اگر عنوان و بدنه یکسان باشند یا متن خیلی کوتاه باشد،
    # عنوان بولد تکراری بالای متن گذاشته نمی‌شود تا فرمت تک‌متن تمیز باشد.
    is_short = (
        not title
        or title == body
        or (len(body) <= 220 and (title in body or body.startswith(title[:40])))
    )

    if is_short:
        parts = [f"{bullet} {body}", ""]
    else:
        parts = [f"{bullet} <b>{title}</b>", "", body, ""]

    parts.append(f"[{esc(item.get('source_tag', 'Liverpool FC'))}]")
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
    summary = ""
    if item.get("_is_quote"):
        return f"\U0001F4AC نقل‌قول از: {esc(orig_tag)} ({esc(orig)})"
    else:
        return f"\U0001F517 منبع اصلی: {esc(orig_tag)} ({esc(orig)})"


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
    """متن انگلیسی دست‌نخورده — فقط برای چشم ادمین، روی کانال نمی‌رود.

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

    head = "\U0001F4C4 <b>متن اصلی (انگلیسی)</b>\n"
    if expandable:
        return head + "<blockquote expandable>" + esc(raw) + "</blockquote>"
    return head + esc(raw)


def keyboard(key, mode="manual"):
    """۳ دکمه — رفتار ثابت در هر دو حالت manual/auto:
    1. ترجمه مجدد  → rtr
    2. نسخه آماده انتشار → pub (نسخه تمیز در گروه ادمین)
    3. انتشار در کانال   → s2c (مستقیم روی کانال)"""
    return {
        "inline_keyboard": [
            [{"text": "\U0001F504 ترجمه مجدد", "callback_data": f"rtr:{key}"}],
            [{"text": "\U0001F4E4 نسخه آماده انتشار", "callback_data": f"pub:{key}"}],
            [{"text": "\U0001F4E2 انتشار در کانال", "callback_data": f"s2c:{key}"}],
        ]
    }
