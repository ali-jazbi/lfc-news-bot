"""ترجمه و بازنویسی خبر به فارسی.

زنجیره fallback کاملاً از .env کنترل می‌شود (TRANSLATE_ORDER).
هر سرویس که خطا بدهد، خودکار می‌رود سراغ بعدی.

دو نوع سرویس:
  llm   → مدل زبانی (خروجی JSON ساختاریافته، با واژگان و لحن درست)
  plain → مترجم ساده بدون کلید (deep-translator) — آخرین سنگر
"""
import json
import logging
import re
import time

import requests

import config
import health

log = logging.getLogger("translate")

_proxies = {"http": config.PROXY, "https": config.PROXY} if config.PROXY else None

SYSTEM_PROMPT = """تو مترجم و خبرنگار حرفه‌ای فوتبال هستی که برای کانال هواداران لیورپول در تلگرام می‌نویسی.

قواعد:
1. خبر انگلیسی را به فارسی روان، خبری و طبیعی برگردان. ترجمه تحت‌اللفظی ممنوع است.

1-الف. مهم‌ترین قاعده — زاویه دید متن را عوض نکن:
   تو مترجمی، نه گزارشگر. متن را عیناً با همان زبانی که نوشته شده برگردان.
   اگر خبرنگار اول‌شخص نوشته (مثلاً "I can confirm" یا "my understanding is")، تو هم اول‌شخص بنویس:
   «می‌توانم تأیید کنم...» ، «برداشت من این است که...»
   هرگز آن را به سوم‌شخص تبدیل نکن.

   ✘ ممنوع: «فابریتزیو رومانو، خبرنگار مطرح نقل‌وانتقالات، خبر داد که...»
   ✘ ممنوع: «رومانو تأکید کرد: ...» ، «این خبرنگار ایتالیایی معتقد است...»
   ✔ درست: همان جمله‌های خودش به فارسی، بدون مقدمه و بدون معرفی گوینده.

   دلیل: اسم منبع خودش پایین پست می‌آید؛ تکرارش در متن هم زائد است هم لحن را خراب می‌کند.

1-ب. اگر در خود متن اصلی جمله‌ای از شخص دیگری نقل شده (مثلاً حرف مربی در گزارش سایت باشگاه)،
   فقط آن را داخل « » بگذار و گوینده‌اش را ذکر کن — چون در متن اصلی هم همین طور بوده.
   یعنی ساختار متن اصلی را عیناً نگه دار؛ نه چیزی اضافه کن، نه حذف.
2. اسامی خاص (بازیکن، باشگاه، ورزشگاه) را ترجمه نکن؛ فقط به فارسی آوانگاری کن و از فهرست واژگان زیر پیروی کن.
3. لحن: رسمی ولی صمیمی، مثل کانال‌های خبری فوتبال. از اغراق و نظر شخصی پرهیز کن.
4. اعداد، مبالغ، تاریخ‌ها و نقل‌قول‌ها را دقیق نگه دار. چیزی از خودت اضافه نکن.
5. متن را در ۲ تا ۴ پاراگراف کوتاه بنویس؛ بین ۴۰۰ تا ۸۰۰ کاراکتر. کمتر از ۴۰۰ یعنی خبر را ناقص گفته‌ای.
6. هیچ اسم بازیکن، مربی، عدد یا نقل‌قولی را حذف نکن. خلاصه‌کردن یعنی حذف توضیح اضافه، نه حذف خبر.
7. اصطلاحات فوتبالی را معنایی برگردان، نه کلمه‌به‌کلمه. نمونه خطاهای ممنوع:
   - in the driving seat ← «در موقعیت برتر» (نه «صندلی رانندگی»)
   - win ugly ← «برد بدون نمایش زیبا» (نه «زشت بردن»)
   - the lads dug in ← «بازیکنان مقاومت کردند» (نه «حفاری کردند»)
   - knocking on the door ← «در صف فشار می‌آورد / خود را ثابت کرده بود»
   - low block ← «دفاع فشرده»، wide forward ← «مهاجم کناری / وینگر»
   - far from vintage ← «نمایش درخشانی نبود»، injury-time winner ← «گل پیروزی‌بخش در وقت‌های تلف‌شده»
8. در کل متن فارسی حتی یک کلمه لاتین نباید بماند (مثلاً AXA ← آکسا). اعداد را فارسی بنویس.
9. نقل‌قول را داخل « » بگذار و حتماً بنویس گوینده‌اش کیست.
10. اگر متن توییت است، لینک‌ها و هشتگ‌های اضافی را حذف کن ولی اموجی‌های معنادار را نگه دار.
11. فقط و فقط یک JSON خروجی بده، بدون هیچ توضیح و بدون code fence:
{"title": "عنوان کوتاه فارسی", "body": "متن فارسی", "importance": "high|normal", "tags": ["تگ۱", "تگ۲"]}

importance را فقط وقتی high بگذار که خبر فوری است: نقل‌وانتقال قطعی، مصدومیت مهم، ترکیب رسمی، بیانیه باشگاه."""


def _glossary_block():
    lines = [f"- {k} = {v}" for k, v in config.GLOSSARY.items()]
    return "فهرست واژگان اجباری:\n" + "\n".join(lines)


def _build_prompt(item):
    return (
        f"{SYSTEM_PROMPT}\n\n{_glossary_block()}\n\n"
        f"---\nمنبع: {item.get('source_tag')}\n"
        f"عنوان اصلی: {item.get('title')}\n"
        f"متن اصلی:\n{(item.get('body') or '')[:4000]}\n---\nخروجی JSON:"
    )


def _extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        try:
            return json.loads(m.group(0).replace("\n", " "))
        except Exception:
            return None


# از این سقف رد نمی‌شویم — کپشن عکس در تلگرام ۱۰۲۴ کاراکتر است
# و جای عنوان، منبع و آیدی کانال هم باید بماند.
BODY_LIMIT = 820

_SENT_END = "۰۱۲۳۴۵۶۷۸۹"  # فقط برای جلوگیری از برش وسط عدد


def _trim(text, limit=BODY_LIMIT):
    """کوتاه کردن متن بدون بریدن وسط کلمه یا جمله."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text

    head = text[:limit]
    # ۱) تا آخرین پایان جمله
    best = -1
    for mark in (".", "\u061f", "!", "\u060c\n", "\n", "\u00bb"):
        best = max(best, head.rfind(mark))
    if best > limit * 0.5:
        return head[: best + 1].strip()

    # ۲) دست‌کم تا آخرین فاصله
    sp = head.rfind(" ")
    if sp > 0:
        head = head[:sp]
    return head.strip() + "\u2026"


# این نشانه‌ها یعنی خبر فوری است، حتی اگر مدل تشخیص نداده باشد
HIGH_SIGNALS = (
    "here we go", "official", "confirmed", "medical", "release clause",
    "agreement", "agreed", "signs", "signed", "injury", "ruled out",
    "exclusive", "breaking",
)


def _fix_importance(item, data):
    """مدل‌های کوچک خبر فوری را normal می‌زنند؛ خودمان دوباره قضاوت می‌کنیم."""
    if data.get("importance") == "high":
        return
    if item.get("priority"):
        data["importance"] = "high"
        return
    blob = ((item.get("title") or "") + " " + (item.get("body") or "")).lower()
    if any(s in blob for s in HIGH_SIGNALS):
        data["importance"] = "high"


def _http_error(who, r):
    """پیام خطای خوانا به جای raise_for_status خشک."""
    body = (r.text or "")[:250].replace("\n", " ")
    hint = ""
    if r.status_code in (401, 403):
        hint = " | کلید نامعتبر یا بدون دسترسی"
    elif r.status_code == 400:
        hint = " | درخواست غلط (معمولاً نام مدل یا کلید)"
    elif r.status_code == 404:
        hint = " | آدرس یا نام مدل اشتباه است"
    elif r.status_code == 429:
        hint = " | سقف مصرف پر شده → سرویس بعدی"
    elif r.status_code >= 500:
        hint = " | خطای سرور سرویس‌دهنده"
    return f"{who} HTTP {r.status_code}{hint} | {body}"


# ---------------- موتورها ----------------
def _gemini(prompt, key, model):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + model
        + ":generateContent?key="
        + key
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
    }
    r = requests.post(url, json=payload, timeout=config.REQUEST_TIMEOUT, proxies=_proxies)
    if r.status_code != 200:
        raise RuntimeError(_http_error("gemini", r))
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _openai_like(prompt, key, base_url, model, label):
    """هر سرویسی که API سازگار با OpenAI دارد: DeepSeek، Groq، OpenRouter، OpenCode، ..."""
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url + "/chat/completions"
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if "openrouter" in url:
        headers["HTTP-Referer"] = "https://t.me/LiverpooliRani"
        headers["X-Title"] = "LFC News Bot"
    r = requests.post(
        url,
        headers=headers,
        json={
            "model": model,
            "temperature": 0.3,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=config.REQUEST_TIMEOUT,
        proxies=_proxies,
    )
    if r.status_code != 200:
        raise RuntimeError(_http_error(label, r))
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"{label}: ساختار پاسخ ناشناخته | {str(data)[:200]}")


# ---------------- مترجم ساده (بدون کلید) ----------------
def _apply_glossary(text):
    """اسامی خاص را بعد از ترجمه ماشینی اصلاح می‌کند."""
    for en, fa in config.GLOSSARY.items():
        text = re.sub(re.escape(en), fa, text, flags=re.IGNORECASE)
    return text


def _deep_translate(item):
    """آخرین سنگر: ترجمه ماشینی گوگل، بدون هیچ کلیدی."""
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        raise RuntimeError("پکیج نصب نیست: pip install deep-translator")

    kwargs = {"source": "auto", "target": "fa"}
    if _proxies:
        kwargs["proxies"] = _proxies
    tr = GoogleTranslator(**kwargs)

    title = (item.get("title") or "").strip()
    body = (item.get("body") or "").strip()
    body = re.sub(r"https?://\S+", "", body).strip()

    fa_title = _apply_glossary(tr.translate(title[:900])) if title else ""
    fa_body = ""
    if body:
        # تکه‌تکه می‌فرستیم چون سقف هر درخواست ۵۰۰۰ کاراکتر است
        chunks = [body[i:i + 4500] for i in range(0, min(len(body), 9000), 4500)]
        fa_body = _apply_glossary(" ".join(tr.translate(c) for c in chunks))

    if not fa_body and not fa_title:
        raise RuntimeError("خروجی خالی")

    return {
        "title": fa_title,
        "body": _trim(fa_body or fa_title),
        "importance": "high" if item.get("priority") else "normal",
        "tags": [],
        "machine": True,   # یعنی کیفیت ماشینی است، ادمین باید بازبینی کند
    }


# ---------------- زنجیره ----------------
def _chain():
    """به ترتیب TRANSLATE_ORDER سرویس‌های قابل استفاده را می‌دهد.

    خروجی: (نام نمایشی، نوع, تابع)
    """
    out = []
    for slot in config.TRANSLATE_ORDER:
        slot = slot.strip().lower()

        if slot in ("translate", "translator", "deep_translator", "google"):
            if config.ENABLE_DEEP_TRANSLATOR:
                out.append(("مترجم گوگل", "plain", _deep_translate))
            continue

        if slot == "gemini":
            for k in config.GEMINI_API_KEYS:
                out.append((
                    "gemini/" + config.GEMINI_MODEL, "llm",
                    (lambda p, k=k: _gemini(p, k, config.GEMINI_MODEL)),
                ))
            continue

        cfg = config.LLM_SLOTS.get(slot)
        if not cfg or not cfg["key"] or not cfg["base_url"] or not cfg["model"]:
            continue
        label = cfg["name"]
        out.append((
            label, "llm",
            (lambda p, c=cfg, l=label: _openai_like(p, c["key"], c["base_url"], c["model"], l)),
        ))
    return out


def chain_names():
    """فقط برای لاگ و doctor."""
    return [n for n, _, _ in _chain()]


def translate(item):
    """خروجی: dict با کلیدهای title / body / importance / tags / provider یا None."""
    chain = _chain()
    if not chain:
        log.error(
            "هیچ سرویس ترجمه‌ای فعال نیست. در .env یا یک اسلات LLM پر کن "
            "یا ENABLE_DEEP_TRANSLATOR=true بگذار."
        )
        return None

    # سرویس‌هایی که قطع‌کننده مدار کنارشان گذاشته را رد می‌کنیم
    usable = [c for c in chain if health.is_available(c[0])]
    if not usable:
        # همه در حالت استراحت‌اند — بهتر است دوباره امتحان کنیم تا هیچ خبری ندهیم
        log.warning("همه سرویس‌ها در حالت کول‌داون‌اند — باز هم یک بار امتحان می‌کنم")
        usable = chain
    else:
        for skipped in [c[0] for c in chain if c not in usable]:
            log.info("%s فعلاً کنار گذاشته شده (%dث دیگر)",
                     skipped, health.cooldown_left(skipped))

    prompt = _build_prompt(item)
    errors = []

    for name, kind, fn in usable:
        t0 = time.time()
        try:
            if kind == "plain":
                data = fn(item)
            else:
                data = _extract_json(fn(prompt))

            if data and data.get("body"):
                health.record_ok(name, ms=(time.time() - t0) * 1000)
                health.record_counter("translated")
                if data.get("machine"):
                    health.record_counter("machine_used")
                data.setdefault("title", item.get("title", ""))
                data.setdefault("importance", "normal")
                data.setdefault("tags", [])
                data["body"] = _trim(str(data["body"]))
                data["title"] = str(data["title"]).strip()[:120]
                _fix_importance(item, data)
                data["provider"] = name
                if len(chain) > 1 and name != chain[0][0]:
                    health.record_counter("fallback_used")
                    log.info("ترجمه با سرویس جایگزین انجام شد: %s", name)
                return data

            health.record_fail(name, "خروجی نامعتبر (JSON خراب یا خالی)")
            errors.append(f"{name}: خروجی نامعتبر")
            log.warning("%s: خروجی نامعتبر، می‌روم سراغ بعدی", name)
        except Exception as e:
            health.record_fail(name, e)
            errors.append(f"{name}: {e}")
            log.warning("%s ناموفق → سرویس بعدی | %s", name, e)

    health.record_counter("chain_failed")
    log.error("همه %d سرویس ترجمه شکست خوردند:", len(usable))
    for e in errors:
        log.error("   • %s", e)

    health.alert(
        "\U0001F6A8 <b>هیچ سرویس ترجمه‌ای کار نکرد</b>\nخبر رد شد: "
        + health._esc((item.get("title") or "")[:80])
        + "\n\n" + "\n".join("• " + health._esc(e[:120]) for e in errors)
        + "\n\nبرای جزئیات: /health",
        key="chain-down",
    )
    return None
