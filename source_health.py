"""سیستم سلامت منابع (مرحله ۹) — هر منبع:

    source_id | last_success_at | last_attempt_at | last_item_at |
    consecutive_failures | total_failures | latency_ms | status

Status: healthy | degraded | failed | disabled

قوانین:
  • backoff نمایی با jitter — منبع خراب هر سیکل اذیت نمی‌شود
  • یک منبع خراب هیچ‌وقت کل pipeline را متوقف نمی‌کند (is_due + timeout)
  • fallback: اگر منبع اصلی fail شد، منبع بعدی همان سیکل خوانده می‌شود

جدول در db.py (source_health) ذخیره می‌شود تا از طریق MCP هم قابل پرس‌وجو باشد.
"""
from __future__ import annotations

import logging
import random
import time

import db

log = logging.getLogger("source_health")

# backoff: ۶۰s × 2^n با jitter ±۲۰٪ — سقف ۱ ساعت
BACKOFF_BASE = 60
BACKOFF_MAX = 3600
FAIL_STATUS_AT = 5     # چند شکست پشت‌سرهم → failed
DEGRADED_AT = 2        # چند شکست → degraded


def _backoff_seconds(consecutive: int) -> float:
    if consecutive <= 0:
        return 0.0
    raw = min(BACKOFF_MAX, BACKOFF_BASE * (2 ** (consecutive - 1)))
    return raw * (0.8 + 0.4 * random.random())


def record(source_id: str, ok: bool, items=0, latency_ms=0, error=""):
    """ثبت یک تلاش خواندن منبع — خروجی: status جدید."""
    status = db.record_source_health(
        source_id, ok=ok, items=items, latency_ms=latency_ms, error=error
    )
    if not ok:
        info = db.source_health_status(source_id)
        consec = info.get("consecutive_failures") or 0
        wait = int(_backoff_seconds(consec))
        log.warning("source %s failed (%d consecutive) — backoff %ss",
                    source_id, consec, wait)
    return status


def is_due(source_id: str) -> bool:
    """آیا الان وقت خواندن این منبع است؟ (با در نظر گرفتن backoff)"""
    info = db.source_health_status(source_id)
    if info.get("status") == "disabled":
        return False
    consec = info.get("consecutive_failures") or 0
    if consec == 0:
        return True
    last = info.get("last_attempt_at") or 0
    return time.time() - last >= _backoff_seconds(consec)


def mark_ok(source_id: str, items=0, latency_ms=0):
    return record(source_id, True, items=items, latency_ms=latency_ms)


def mark_fail(source_id: str, error=""):
    return record(source_id, False, error=error)


def report() -> str:
    """خلاصه برای /health — HTML سبک."""
    rows = db.list_source_health()
    if not rows:
        return "هیچ منبعی هنوز ثبت نشده."
    lines = ["\U0001F4E1 <b>سلامت منابع</b>"]
    icons = {"healthy": "\u2705", "degraded": "\u26a0\ufe0f",
             "failed": "\u274c", "disabled": "\u26d4"}
    for r in rows:
        consec = r.get("consecutive_failures") or 0
        extra = ""
        if consec >= 2:
            extra = f" · {consec} شکست پشت\u200cسرهم"
        ok = r.get("total_ok") or 0
        fail = r.get("total_failures") or 0
        total = ok + fail
        rate = int(ok * 100 / total) if total else 0
        lines.append(
            f"{icons.get(r['status'], '•')} <b>{r['source_id']}</b> — "
            f"{r['status']} ({rate}% موفق){extra}"
        )
    return "\n".join(lines)
