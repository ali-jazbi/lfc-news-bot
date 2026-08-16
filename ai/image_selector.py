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
    """همه کاندیداها به ترتیب اولویت — هر کاندیدا یک dict با metadata:

        {url, kind: "article"|"search", source}

    1) عکس اصلی خبر (article)   2) آلبوم خبر (article)   3) thumbnail ویدیو
    4) جستجوی خودکار (search — فقط اگر روشن است و خبر عکس نداشته باشد)
    """
    out = []
    seen = set()

    def _add(u, kind, source="article"):
        if u and u not in seen and str(u).startswith(("http", "/")):
            seen.add(u)
            out.append({"url": str(u), "kind": kind, "source": source})

    for u in [item.get("image")]:
        _add(u, "article", "article main image")
    for u in (item.get("images") or [])[:limit]:
        _add(u, "article", "article gallery")
    if item.get("video_thumb"):
        _add(item["video_thumb"], "article", "video thumbnail")

    # جستجوی خودکار فقط وقتی روشن باشد و خبر عکس نداشته باشد
    has_article = any(c["kind"] == "article" for c in out)
    if not has_article and getattr(config, "ENABLE_AUTO_IMAGE", False):
        try:
            from sources.webimg import find_for_article, is_live_update
            if not is_live_update(item):
                auto = find_for_article(
                    item.get("title") or "", item.get("body") or "",
                    item.get("url") or "",
                    timeout=getattr(config, "WEBIMG_TIMEOUT", 8),
                )
                if auto:
                    _add(auto, "search", "auto web search")
        except Exception as e:
            log.debug("auto image search failed: %s", e)
    return out[:limit]


def select_image(item: dict, editor=None):
    """انتخاب نهایی عکس — خروجی (image_url|None, ImageSelection).

    fail-safe (مرحله ۱۰):
      • عکس منبع داریم → AI خراب بود → همان عکس منبع می‌ماند
      • عکس منبع نداریم → AI خراب بود → بدون عکس (هرگز auto بدون validation)
    """
    nid = news_id_of(item)
    candidates = candidate_images(item)
    trace(nid, "IMAGE", candidates=len(candidates))

    article_cands = [c for c in candidates if c["kind"] == "article"]
    source_img = (article_cands[0]["url"] if article_cands else None)

    if not candidates:
        trace(nid, "IMAGE", selected="none", reason="no candidates")
        return None, None

    # AI خاموش → فقط عکسِ خودِ منبع؛ بدون عکس منبع → هیچ عکسی (حتی auto)
    if not config.HERMES_ENABLED or editor is None:
        trace(nid, "IMAGE", selected=source_img,
              reason="source image (AI off)" if source_img else "no image (AI off)")
        return source_img, None

    try:
        sel = editor.client.select_image(item, candidates)
    except Exception as e:
        log.warning("image evaluation crashed (%s) — source image only", e)
        trace(nid, "IMAGE", selected=source_img,
              reason="AI crashed — source image" if source_img
              else "AI crashed — no image")
        # fail-safe: هرگز auto-search result بدون validation انتخاب نمی‌شود
        return source_img, None

    if sel.image_url:
        # اگر AI عکسی را انتخاب کرد، باید یکی از کاندیداها باشد (validation)
        if sel.image_url not in seen_urls(candidates):
            log.warning("AI picked an image not in candidates — dropping")
            trace(nid, "IMAGE", selected="none", reason="untrusted url")
            return source_img, None
        trace(nid, "IMAGE", selected=sel.image_url,
              confidence=round(sel.confidence, 2))
        return sel.image_url, sel
    trace(nid, "IMAGE", selected="none", reason=sel.reason or "low confidence")
    return None, sel


def seen_urls(candidates: list) -> set:
    return {c["url"] for c in candidates}
