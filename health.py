"""سلامت و مانیتورینگ سرویس‌ها.

سه کار می‌کند:
  1) آمار موفقیت/شکست هر سرویس را روی دیسک نگه می‌دارد
     (با ریست شدن ربات هم پاک نمی‌شود)
  2) قطع‌کننده مدار (circuit breaker): سرویسی که پشت‌سر‌هم خطا می‌دهد
     مدتی کنار گذاشته می‌شود تا وقت هدر ندهد
  3) وضعیت را برای گزارش ادمین آماده می‌کند؛ تغییر مدار پیام خودکار ندارد

عمداً هیچ وابستگی به telegram_api ندارد تا حلقه import نسازد؛
ارسال پیام را main.py با set_notifier تزریق می‌کند.
"""
import json
import logging
import os
import shutil
import threading
import time
import re
from contextlib import contextmanager

log = logging.getLogger("health")

STATE_PATH = os.path.join("data", "health.json")

# Legacy source failure policy; translation providers use failure_policy below.
FAIL_LIMIT = 3
# Source cooldown steps in seconds.
COOLDOWN_STEPS = [300, 900, 3600, 21600]

_lock = threading.RLock()
_inflight = set()
_notifier = None          # تابعی که پیام به ادمین می‌فرستد
_alerted = set()          # تا خرابی رفع نشده، دوباره هشدار ندهیم

_state = {
    "provider_gate_version": 2,
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
        "error_code": "",
    }


def load():
    global _state
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for k in ("providers", "sources", "counters"):
            data.setdefault(k, {})
        # Retire legacy escalating cooldowns; keep historical counters intact.
        migrated = data.get("provider_gate_version") != 2
        if migrated:
            try:
                folder = os.path.join(os.path.dirname(STATE_PATH) or '.', 'backups')
                os.makedirs(folder, exist_ok=True)
                shutil.copy2(STATE_PATH, os.path.join(folder, f'pre-provider-health-{time.time_ns()}.json'))
            except OSError as exc:
                _state = data
                log.error('health migration deferred: backup failed (%s)', exc)
                return
            for b in data["providers"].values():
                b.update(cooldown_until=0, streak=0, error_code="")
            data["provider_gate_version"] = 2
        _state = data
        if migrated:
            save()
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
        log.debug("failed to save health: %s", e)


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
            log.error("failed to send alert: %s", e)


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
        b["error_code"] = ""
        if ms:
            n = min(b["ok"], 20)
            b["avg_ms"] = int((b["avg_ms"] * (n - 1) + ms) / n) if n > 1 else int(ms)
        save()
    if was_down:
        clear_alert("down:" + name)
        log.info("service recovered: %s", name)


def failure_policy(error):
    """One circuit policy for translation, QC and machine fallback."""
    text = str(error).casefold()
    if "invalid review" in text:
        return "invalid_review", 180
    if any(x in text for x in ("invalid translation", "invalid output")):
        return "invalid_output", 0
    if any(x in text for x in ("unavailable for free", "notfounderror", "model not found", "does not exist", "404")):
        return "model_unavailable", 21600
    if any(x in text for x in ("authenticationerror", "invalid api key", "401", "unauthorized")):
        return "authentication", 3600
    if any(x in text for x in ("rate limit", "ratelimit", "too many requests", "429", "overloaded")):
        delay = 60 if "overloaded" in text else 180
        headers = getattr(getattr(error, "response", None), "headers", {}) or {}
        try:
            delay = max(1, float(headers.get("retry-after", delay)))
        except (ValueError, TypeError):
            pass
        match = re.search(r'(?:try again in|retry after)\s*(?:(\d+(?:\.\d+)?)h)?\s*(?:(\d+(?:\.\d+)?)m)?\s*(?:(\d+(?:\.\d+)?)s)?', text)
        if match and any(match.groups()):
            delay = sum(float(n or 0) * scale for n, scale in zip(match.groups(), (3600, 60, 1)))
        return "rate_limit", min(max(delay, 1), 86400)
    return "temporary_error", 30


def record_fail(name, error="", kind="provider", *, code=None, retry_after=None):
    with _lock:
        b = _bucket(kind).setdefault(name, _blank())
        b["fail"] += 1
        b["streak"] += 1
        b["last_fail"] = int(time.time())
        b["last_error"] = str(error)[:220]
        streak = b["streak"]

        if kind == "provider":
            inferred_code, delay = failure_policy(error)
            b["error_code"] = code or inferred_code
            delay = delay if retry_after is None else retry_after
            if b["error_code"] == "invalid_output":
                delay = 180 if streak >= 2 else 0
            b["cooldown_until"] = time.time() + delay
            if delay:
                b["outages"] += 1
        elif streak >= FAIL_LIMIT:
            step = min((streak - FAIL_LIMIT) // FAIL_LIMIT, len(COOLDOWN_STEPS) - 1)
            cd = COOLDOWN_STEPS[step]
            b["cooldown_until"] = time.time() + cd
            if streak == FAIL_LIMIT:
                b["outages"] += 1
        save()

    log.debug("service failure recorded: %s (%s)", name, b.get("error_code", "source"))


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


@contextmanager
def provider_slot(name):
    """Never probe a cooling-down provider or overlap its translation/QC calls."""
    with _lock:
        allowed = is_available(name) and name not in _inflight
        if allowed:
            _inflight.add(name)
    try:
        yield allowed
    finally:
        if allowed:
            with _lock:
                _inflight.discard(name)


def next_provider_retry(names):
    now = time.time()
    return min((max(now + 15, stats(n).get("cooldown_until", 0)) for n in names), default=now + 300)


def provider_status(name):
    left = cooldown_left(name)
    if left:
        return "موقتاً متوقف — " + _fmt_dur(left) + " تا تلاش بعدی"
    with _lock:
        return "در حال درخواست" if name in _inflight else "آمادهٔ تلاش"


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

    out.append("\U0001F9E0 <b>سرویس‌های ترجمه</b> (آمار تجمعی درخواست‌های ترجمه و بازبینی)")
    names = chain_names or list(_state["providers"].keys())
    if not names:
        out.append("➖ هیچ سرویسی تعریف نشده")
    for i, n in enumerate(names, 1):
        out.append(str(i) + ". " + _line(n, _state["providers"].get(n) or _blank()))

    if _state["sources"]:
        out += ["", "\U0001F4E1 <b>منابع خبری</b> (موفقیت دریافت؛ نه ارتباط خبر)"]
        for n, b in _state["sources"].items():
            out.append("• " + _line(n, b))

    c = _state["counters"]
    if c:
        out += ["", "\U0001F522 <b>آمار تجمعی</b>"]
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
        out.append("⏳ فعلاً سرویسی آمادهٔ تلاش نیست؛ خبرها در صف می‌مانند. دلیل هر توقف بالاتر آمده است.")
    return "\n".join(out)


load()
