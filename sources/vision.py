"""تحلیل AI عکس/ویدیو — تشخیص مرتبط بودن با لیورپول.

برای توییت‌های عکسی/ویدیوییِ خبرنگاران که متنشان کلمه لیورپولی ندارد، عکس
(یا پوستر ویدیو) با یک مدل بینا (vision) تحلیل می‌شود: اگر به لیورپول مرتبط
بود، خبر با برچسب ⚠ به گروه ادمین می‌رود تا ادمین خودش بازبینی کند.

چرا جدا از translate: زنجیره ترجمه برای متن است؛ این ماژول فقط «بله/خیر»
می‌پرسد و خروجی بسیار کوچک (یک کلمه) می‌گیرد، پس جدا و ارزان‌تر است.

نکته: فقط مدل‌های vision جواب می‌دهند. تست زنده نشان داد qwen3.7-plus
(VISION_SLOT=llm6) تنها مدل بینای زنجیره است.
"""
import base64
import logging
import re
import time

import config
import health

log = logging.getLogger("src.vision")

_REVIEW_PROMPT = (
    "Is this image related to Liverpool FC (Liverpool players, the club badge, "
    "the red kit, Anfield, an LFC match or event, an LFC transfer story)? "
    "Reply with exactly one word: yes or no"
)


def _slot_cfg():
    slot = getattr(config, "VISION_SLOT", "llm6") or "llm6"
    return config.LLM_SLOTS.get(slot)


def _fetch_image_b64(url, timeout=25):
    """عکس را دانلود و به base64 تبدیل می‌کند — خروجی None اگر نشد."""
    if not url or not str(url).startswith("http"):
        return None
    import requests
    try:
        r = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=timeout)
        ctype = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "image" in ctype and len(r.content) > 512:
            return base64.b64encode(r.content).decode()
        log.debug("vision: دانلود عکس %s → HTTP %s (%s)", url[:70], r.status_code, ctype)
    except Exception as e:
        log.debug("vision: دانلود عکس خطا: %s", e)
    return None


def classify(url, timeout=60):
    """True = به لیورپول مرتبط است. False = مرتبط نیست. None = نتوانست قضاوت کند.

    خروجی None یعنی «به حالت قبل برمی‌گردیم» یعنی همان ردِ عادی — امن است،
    خبر از دست نمی‌رود چون قرار بود همین حالا هم رد شود.
    """
    cfg = _slot_cfg()
    if not cfg or not cfg["key"] or not cfg["base_url"] or not cfg["model"]:
        log.warning("vision: اسلات %s تنظیم نشده", getattr(config, "VISION_SLOT", "llm6"))
        return None

    b64 = _fetch_image_b64(url)
    if not b64:
        return None

    params = {
        "model": "openai/" + cfg["model"],
        "api_base": cfg["base_url"].rstrip("/"),
        "api_key": cfg["key"],
        "timeout": timeout,
    }
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": _REVIEW_PROMPT},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ],
    }]

    t0 = time.time()
    try:
        from litellm import completion
        resp = completion(messages=messages, max_tokens=8, temperature=0, **params)
        raw = resp.choices[0].message.content or ""
        health.record_ok("vision", ms=(time.time() - t0) * 1000, kind="source")
        m = re.search(r"\b(yes|no)\b", raw, re.I)
        if not m:
            log.debug("vision: جواب نامفهوم: %s", raw[:80])
            return None
        verdict = m.group(1).lower() == "yes"
        log.info("vision: عکس %s → %s (%s)", url[:60], verdict, cfg["model"])
        return verdict
    except Exception as e:
        health.record_fail("vision", e, kind="source")
        log.debug("vision: خطای مدل: %s", e)
        return None
