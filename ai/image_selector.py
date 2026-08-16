"""هوش عکس (مرحله ۷) — حل مشکل «خبر بدون عکس → عکس نامناسب».

Pipeline:
    کاندیداها (عکس خودِ خبر + نتایج جستجو)
        ↓
    ارزیابی AI (relevance / بازیکن درست / تیم درست / کیفیت)
        ↓
    اگر اطمینان پایین → بدون عکس (هرگز عکس تصادفی)

قانون طلایی: better no image than a wrong image.
اگر AI خاموش باشد: عکسِ خودِ منبع (اگر هست) می‌ماند؛ هیچ عکسِ جدیدِ
تصادفی‌ای اضافه نمی‌شود.
"""
from __future__ import annotations

import logging

import config

from .tracing import trace, news_id_of

log = logging.getLogger("ai.image")


def candidate_images(item: dict, limit=8) -> list:
    """همه کاندیداها به ترتیب اولویت:
    1) عکس اصلی خبر   2) آلبوم خبر   3) جستجوی خودکار (فقط اگر روشن است)
    """
    out = []
    seen = set()

    def _add(u):
        if u and u not in seen and str(u).startswith(("http", "/")):
            seen.add(u)
            out.append(str(u))

    _add(item.get("image"))
    for u in (item.get("images") or [])[:limit]:
        _add(u)
    if item.get("video_thumb"):
        _add(item["video_thumb"])

    # جستجوی خودکار فقط وقتی روشن باشد و خبر عکس نداشته باشد
    if not out and getattr(config, "ENABLE_AUTO_IMAGE", False):
        try:
            from sources.webimg import find_for_article, is_live_update
            if not is_live_update(item):
                auto = find_for_article(
                    item.get("title") or "", item.get("body") or "",
                    item.get("url") or "",
                    timeout=getattr(config, "WEBIMG_TIMEOUT", 8),
                )
                _add(auto)
        except Exception as e:
            log.debug("auto image search failed: %s", e)
    return out[:limit]


def select_image(item: dict, editor=None):
    """انتخاب نهایی عکس — خروجی (image_url|None, ImageSelection)."""
    nid = news_id_of(item)
    candidates = candidate_images(item)
    trace(nid, "IMAGE", candidates=len(candidates))

    if not candidates:
        trace(nid, "IMAGE", selected="none", reason="no candidates")
        return None, None

    # AI خاموش → فقط عکسِ خودِ منبع (رفتار فعلی، بدون عکسِ تصادفی)
    if not config.HERMES_ENABLED or editor is None:
        own = item.get("image") or candidates[0]
        trace(nid, "IMAGE", selected=own, reason="source image (AI off)")
        return own, None

    try:
        sel = editor.client.select_image(item, candidates)
    except Exception as e:
        log.warning("image evaluation crashed (%s) — keeping source image only", e)
        own = item.get("image") or candidates[0]
        trace(nid, "IMAGE", selected=own, reason="AI crashed — source image")
        return own, None
    if sel.image_url:
        trace(nid, "IMAGE", selected=sel.image_url,
              confidence=round(sel.confidence, 2))
        return sel.image_url, sel
    trace(nid, "IMAGE", selected="none", reason=sel.reason or "low confidence")
    return None, sel
