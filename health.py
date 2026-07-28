"""سلامت و مانیتورینگ سرویس‌ها.

سه کار می‌کند:
  1) آمار موفقیت/شکست هر سرویس را روی دیسک نگه می‌دارد
     (با ریست شدن ربات هم پاک نمی‌شود)
  2) قطع‌کننده مدار (circuit breaker): سرویسی که پشت‌سر‌هم خطا می‌دهد
     مدتی کنار گذاشته می‌شود تا وقت هدر ندهد
  3) هشدار تلگرامی به ادمین وقتی چیزی خراب می‌شود

عمداً هیچ وابستگی به telegram_api ندارد تا حلقه import نسازد؛
ارسال پیام را main.py با set_notifier تزریق می‌کند.
"""
import json
import logging
import os
import threading
import time

log = logging.getLogger("health")

STATE_PATH = os.path.join("data", "health.json")

# بعد از چند خطای پشت‌سر‌هم، سرویس موقتاً کنار گذاشته شود
FAIL_LIMIT = 3
# مدت کنارگذاشتن (ثانیه) — پلکانی: ۵ دقیقه، ۱۵ دقیقه، ۱ ساعت، ۶ ساعت
COOLDOWN_STEPS = [300, 900, 3600, 21600]

_lock = threading.Lock()
_notifier = None          # تابعی که پیام به ادمین می‌فرستد
_alerted = set()          # تا خرابی رفع نشده، دوباره هشدار ندهیم

_state = {
    "providers": {},   # نام سرویس → آمار
    "sources": {},     # نام منبع خبری → آمار
    "counters": {},    # شمارنده‌های عمومی
}


# ------------------------------------------------------------------ ذخیره
def _blank():
    return {
        "ok": 0,
        "fail": 0,
        "streak": 0,          # خطای پشت‌سر‌هم فعلی
        "outages": 0,         # چند بار کلاً از مدار خارج شده
        "last_ok": None,
        "last_fail": None,
        "last_error": "",
        "cooldown_until": 0,
        "avg_ms": 0,
    }


def load():
    global _state
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for k in ("providers", "sources", "counters"):
            data.setdefault(k, {})
        _state = data
    except Exception:
        pass


def save():
    try:
        os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_PATH)
    except Exception as e:
        log.debug("ذخیره health ناموفق: %s", e)


# ------------------------------------------------------------------ هشدار
def set_notifier(fn):
    """main.py یک تابع send_message می‌دهد."""
    global _notifier
    _notifier = fn


def alert(text, key=None, once=True):
    """هشدار به گروه ادمین. با key مشخص، تا رفع نشدن تکرار نمی‌شود."""
    if once and key:
        if key in _alerted:
            return
        _alerted.add(key)
    log.warning("ALERT | %s", text.replace("\n", " ")[:300])
    if _notifier:
        try:
            _notifier(text)
        except Exception as e:
            log.error("ارسال هشدار ناموفق: %s", e)


def clear_alert(key):
    _alerted.discard(key)


# ------------------------------------------------------------------ ثبت
def _bucket(kind):
    return _state["sources"] if kind == "source" else _state["providers"]


def record_ok(name, ms=0, kind="provider"):
    with _lock:
        b = _bucket(kind).setdefault(name, _blank())
        was_down = b["streak"] >= FAIL_LIMIT
        b["ok"] += 1
        b["streak"] = 0
        b["cooldown_until"] = 0
        b["last_ok"] = int(time.time())
        b["last_error"] = ""
        if ms:
            n = min(b["ok"], 20)
            b["avg_ms"] = int((b["avg_ms"] * (n - 1) + ms) / n) if n > 1 else int(ms)
        save()
    if was_down:
        clear_alert("down:" + name)
        alert("\u2705 دوباره سر پا شد: <b>" + _esc(name) + "</b>", once=False)


def record_fail(name, error="", kind="provider"):
    with _lock:
        b = _bucket(kind).setdefault(name, _blank())
        b["fail"] += 1
        b["streak"] += 1
        b["last_fail"] = int(time.time())
        b["last_error"] = str(error)[:220]
        streak = b["streak"]

        if streak >= FAIL_LIMIT:
            step = min((streak - FAIL_LIMIT) // FAIL_LIMIT, len(COOLDOWN_STEPS) - 1)
            cd = COOLDOWN_STEPS[step]
            b["cooldown_until"] = time.time() + cd
            if streak == FAIL_LIMIT:
                b["outages"] += 1
        save()

    if streak == FAIL_LIMIT:
        alert(
            "\u26a0\ufe0f سرویس <b>" + _esc(name) + "</b> از مدار خارج شد\n"
            + "دلیل: <code>" + _esc(str(error)[:150]) + "</code>\n"
            + "فعلاً رد می‌شود و سرویس بعدی زنجیره کار را ادامه می‌دهد.",
            key="down:" + name,
        )


def record_counter(name, n=1):
    with _lock:
        _state["counters"][name] = _state["counters"].get(name, 0) + n


# ------------------------------------------------------------------ پرس‌وجو
def is_available(name, kind="provider"):
    b = _bucket(kind).get(name)
    if not b:
        return True
    return time.time() >= b.get("cooldown_until", 0)


def cooldown_left(name, kind="provider"):
    b = _bucket(kind).get(name)
    if not b:
        return 0
    return max(0, int(b.get("cooldown_until", 0) - time.time()))


def stats(name, kind="provider"):
    return dict(_bucket(kind).get(name) or _blank())


def _esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _ago(ts):
    if not ts:
        return "هرگز"
    d = int(time.time() - ts)
    if d < 60:
        return str(d) + " ثانیه پیش"
    if d < 3600:
        return str(d // 60) + " دقیقه پیش"
    if d < 86400:
        return str(d // 3600) + " ساعت پیش"
    return str(d // 86400) + " روز پیش"


def _fmt_dur(s):
    if s <= 0:
        return ""
    if s < 60:
        return str(s) + " ثانیه"
    if s < 3600:
        return str(s // 60) + " دقیقه"
    return str(s // 3600) + " ساعت"


def _line(name, b):
    total = b["ok"] + b["fail"]
    left = max(0, int(b.get("cooldown_until", 0) - time.time()))
    if left > 0:
        icon = "\u26d4"
    elif b["streak"] > 0:
        icon = "\u26a0\ufe0f"
    elif total == 0:
        icon = "\u2796"
    else:
        icon = "\u2705"

    rate = int(b["ok"] * 100 / total) if total else 0
    txt = icon + " <b>" + _esc(name) + "</b>"
    if total:
        txt += "  —  " + str(rate) + "% موفق (" + str(b["ok"]) + "/" + str(total) + ")"
    if b.get("avg_ms"):
        txt += " · " + str(round(b["avg_ms"] / 1000, 1)) + "s"
    if left > 0:
        txt += "\n    ⏳ تا " + _fmt_dur(left) + " دیگر کنار گذاشته شده"
    if b["last_error"] and b["streak"] > 0:
        txt += "\n    ↳ <code>" + _esc(b["last_error"][:110]) + "</code>"
    return txt


def report(chain_names=None):
    """متن HTML برای دستور /health."""
    out = ["\U0001F4CA <b>وضعیت سرویس‌ها</b>", ""]

    out.append("\U0001F9E0 <b>سرویس‌های ترجمه</b> (به ترتیب اولویت)")
    names = chain_names or list(_state["providers"].keys())
    if not names:
        out.append("➖ هیچ سرویسی تعریف نشده")
    for i, n in enumerate(names, 1):
        out.append(str(i) + ". " + _line(n, _state["providers"].get(n) or _blank()))

    if _state["sources"]:
        out += ["", "\U0001F4E1 <b>منابع خبری</b>"]
        for n, b in _state["sources"].items():
            out.append("• " + _line(n, b))

    c = _state["counters"]
    if c:
        out += ["", "\U0001F522 <b>آمار</b>"]
        labels = {
            "translated": "خبر ترجمه‌شده",
            "chain_failed": "شکست کامل زنجیره",
            "fallback_used": "استفاده از سرویس جایگزین",
            "machine_used": "ترجمه ماشینی خام",
            "cycles": "سیکل چک منابع",
        }
        for k, v in c.items():
            out.append("• " + labels.get(k, k) + ": " + str(v))

    alive = [n for n in names if is_available(n)]
    out += ["", "سرویس فعال در مدار: <b>" + str(len(alive)) + " از " + str(len(names)) + "</b>"]
    if not alive and names:
        out.append("\u274c هیچ سرویسی سالم نیست — کلیدها را چک کن")
    return "\n".join(out)


load()
