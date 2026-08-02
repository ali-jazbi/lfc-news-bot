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

log = logging.getLogger("src.vision")

# کش نتیجه قضاوت: کلید = URL عکس + متن کوتاه، مقدار = (زمان, verdict).
# چون توییت‌های ردشده هر سیکل دوباره نامزد می‌شوند، بدون این کش هر سیکل
# دوباره به مدل می‌زدیم و سقف روزانه‌ی llm6 (که هم برای vision است هم ترجمه)
# زود پر می‌شد.
_VISION_CACHE = {}
_VISION_CACHE_TTL = 6 * 3600      # ۶ ساعت — توییت ردشده دوباره تحلیل نمی‌شود


def _cache_key(url, text):
    return (url or "")[:120] + "|" + (text or "")[:60]

_REVIEW_PROMPT = (
    "You are checking a football journalist's tweet for a Liverpool FC (LFC) "
    "news channel. Decide if this tweet is genuinely about Liverpool FC.\n"
    "You get the tweet text AND the attached photo/video poster.\n\n"
    "Answer YES only if the photo clearly shows LFC (the club badge, a player "
    "in the current Liverpool kit with LFC branding, Anfield, an LFC training "
    "session or match) AND the text does not say the player is at a different club.\n\n"
    "Answer NO if ANY of these is true:\n"
    "- The text names another club, stadium, or team the player now plays for "
    "  (e.g. 'Chicago Fire', 'his new team', 'Newcastle') — the person is NOT "
    "  an LFC player even in a red shirt.\n"
    "- The photo is just a generic red kit with no LFC branding, or a former "
    "  LFC player at another club.\n"
    "- There is no clear LFC connection.\n\n"
    "If you are unsure, answer no.\n"
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


def classify(url, text="", timeout=60):
    """True = به لیورپول مرتبط است. False = مرتبط نیست. None = نتوانست قضاوت کند.

    text = متن توییت (اختیاری ولی مهم) — به مدل کمک می‌کند بفهمد بازیکن
    متعلق به کدام تیم است، حتی اگر عکس قرمز باشد.

    خروجی None یعنی «به حالت قبل برمی‌گردیم» یعنی همان ردِ عادی — امن است،
    خبر از دست نمی‌رود چون قرار بود همین حالا هم رد شود.
    """
    cfg = _slot_cfg()
    if not cfg or not cfg["key"] or not cfg["base_url"] or not cfg["model"]:
        log.warning("vision: اسلات %s تنظیم نشده", getattr(config, "VISION_SLOT", "llm6"))
        return None

    # کش: همین عکس+متن قبلاً قضاوت شده؟ (جلوگیری از هدر دادن سقف روزانه)
    ck = _cache_key(url, text)
    hit = _VISION_CACHE.get(ck)
    if hit and time.time() - hit[0] < _VISION_CACHE_TTL:
        log.debug("vision: کش %s → %s", url[:50], hit[1])
        return hit[1]

    b64 = _fetch_image_b64(url)
    if not b64:
        return None

    params = {
        "model": "openai/" + cfg["model"],
        "api_base": cfg["base_url"].rstrip("/"),
        "api_key": cfg["key"],
        "timeout": timeout,
    }
    prompt = _REVIEW_PROMPT
    if text:
        prompt += "\n\nTweet text: " + (text[:400] or "")
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ],
    }]

    try:
        from litellm import completion
        resp = completion(messages=messages, max_tokens=8, temperature=0, **params)
        raw = resp.choices[0].message.content or ""
        m = re.search(r"\b(yes|no)\b", raw, re.I)
        if not m:
            log.debug("vision: جواب نامفهوم: %s", raw[:80])
            _remember(ck, None)
            return None
        verdict = m.group(1).lower() == "yes"
        _remember(ck, verdict)
        log.info("vision: عکس %s → %s (%s)", url[:60], verdict, cfg["model"])
        return verdict
    except Exception as e:
        # خطای مدل (مثل rate limit) — فقط لاگ، بدون هشدار به گروه ادمین.
        # vision یک قابلیت کمکی best-effort است؛ خرابی‌اش نباید گروه را اذیت کند.
        log.info("vision: خطای مدل (%s) — رد می‌شود: %s", cfg["model"], str(e)[:80])
        return None


def _remember(ck, verdict):
    """نتیجه را کش می‌کند تا توییتِ ردشده هر سیکل دوباره تحلیل نشود.

    ck از _cache_key(url, text) ساخته شده؛ verdict می‌تواند True/False/None
    باشد (None یعنی نامشخص — باز هم تحلیل مجدد لازم نیست).
    """
    _VISION_CACHE[ck] = (time.time(), verdict)
    if len(_VISION_CACHE) > 512:
        _VISION_CACHE.pop(next(iter(_VISION_CACHE)))
