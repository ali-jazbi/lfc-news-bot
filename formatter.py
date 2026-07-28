"""ساخت قالب پست تلگرام مطابق تمپلیت کانال."""
import html

import config


def esc(t):
    return html.escape(t or "", quote=False)


def build_caption(item, tr):
    """نسخه نهایی و تمیز پست — دقیقاً همانی که روی کانال می‌رود."""
    bullet = "\U0001F534" if tr.get("importance") == "high" else "\u26AA\uFE0F"
    body = esc(tr["body"]).strip()
    parts = [f"{bullet} <b>{esc(tr.get('title',''))}</b>", "", body, ""]
    parts.append(f"[{esc(item.get('source_tag','Liverpool FC'))}]")
    parts.append(config.CHANNEL_USERNAME)
    return "\n".join(parts)


def build_admin_caption(item, tr):
    """نسخه پیش‌نمایش در گروه ادمین‌ها (با لینک منبع و اطلاعات فنی)."""
    caption = build_caption(item, tr)
    src = item.get("url", "")
    tail = f"\n\n\u2500\u2500\u2500\n\U0001F517 <a href=\"{esc(src)}\">منبع اصلی</a>"
    if tr.get("provider"):
        tail += f" | ترجمه: {esc(str(tr['provider']))}"
    if tr.get("machine"):
        tail += "\n\u26A0\uFE0F ترجمه ماشینی — قبل از انتشار متن را بازبینی کن"
    return caption + tail


def build_original_message(item, expandable=True):
    """متن انگلیسی دست‌نخورده — فقط برای چشم ادمین، روی کانال نمی‌رود.

    در بلاک‌کووت تاشو گذاشته می‌شود تا گروه را شلوغ نکند؛
    ادمین رویش بزند باز می‌شود.
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

    head = "\U0001F4C4 <b>متن اصلی (انگلیسی)</b>\n"
    if expandable:
        return head + "<blockquote expandable>" + esc(raw) + "</blockquote>"
    return head + esc(raw)


def keyboard(key, mode="manual"):
    """mode=manual  → ربات فقط نسخه تمیز را می‌دهد، ادمین خودش کپی/فوروارد می‌کند
    mode=auto    → ربات مستقیم روی کانال می‌فرستد"""
    first = (
        "\U0001F4E4 نسخه آماده انتشار"
        if mode == "manual"
        else "\u2705 انتشار در کانال"
    )
    return {
        "inline_keyboard": [
            [
                {"text": first, "callback_data": f"pub:{key}"},
                {"text": "\u274C رد", "callback_data": f"rej:{key}"},
            ],
            [{"text": "\U0001F504 ترجمه مجدد", "callback_data": f"rtr:{key}"}],
        ]
    }
