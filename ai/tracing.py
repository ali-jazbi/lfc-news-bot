"""ردیابی هر خبر (مرحله ۱۴) — یک trace واضح برای هر NEWS_ID.

فرمت:
    NEWS_ID=1234 [FETCH] source=bbc success=true
    NEWS_ID=1234 [AI_ANALYSIS] decision=publish confidence=0.91 importance=8
    ...

همه‌چیز در لاگ استاندارد (file+console) می‌رود تا با بقیه سیستم یکی باشد.
"""
from __future__ import annotations

import logging

log = logging.getLogger("trace")


def trace(news_id, stage: str, **fields):
    if not news_id:
        news_id = "?"
    parts = []
    for k, v in fields.items():
        if v is None:
            continue
        if isinstance(v, bool):
            v = "true" if v else "false"
        s = str(v).replace("\n", " ").strip()
        if len(s) > 120:
            s = s[:117] + "..."
        parts.append(f"{k}={s}")
    line = f"NEWS_ID={news_id} [{stage}] " + " ".join(parts)
    log.info(line.rstrip())


def news_id_of(item) -> str:
    """کلید کوتاه خبر برای trace — از db.make_key اگر موجود وگرنه عنوان."""
    try:
        import db
        return db.make_key(item or {})[:10]
    except Exception:
        t = (item or {}).get("title") or ""
        return str(abs(hash(t)))[:10]
