"""ترجمه و بازنویسی خبر به فارسی — نسخه LiteLLM (فقط برای حالت دولوپ).

تفاوت با نسخه قبلی:
  • مدیریت زنجیره، retry، backoff و cooldown را LiteLLM Router انجام می‌دهد.
  • مدلی که چند بار پشت‌سرهم خطا بدهد، خودکار چند دقیقه کنار گذاشته می‌شود
    (یعنی دیگر برای هر خبر پای تایم‌اوت مدل مرده نمی‌سوزیم).
  • رابط بیرونی دست‌نخورده است: translate(item) و chain_names() مثل قبل.

نصب:  pip install "litellm>=1.55"

کلیدهای اختیاری .env:
  LLM_COOLDOWN_SECONDS=180   چند ثانیه یک مدل خراب کنار گذاشته شود
  LLM_NUM_RETRIES=1          چند بار تلاش مجدد روی همان مدل قبل از رفتن به بعدی
  LLM_ALLOWED_FAILS=2        چند خطای پشت‌سرهم = کنار گذاشتن مدل
  TRANSLATE_JSON_MODE=false  اجبار خروجی JSON (بعضی مدل‌های رایگان پشتیبانی نمی‌کنند)
"""
import json
import logging
import os
import re
import time

import config
import health

log = logging.getLogger("translate")

_proxies = {"http": config.PROXY, "https": config.PROXY} if config.PROXY else None

try:
    import litellm
    from litellm import Router

    litellm.suppress_debug_info = True
    litellm.drop_params = True          # پارامتری که مدل پشتیبانی نکند، حذف می‌شود
    litellm.set_verbose = False
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)   # خفه‌کردن هشدار cost map
    _HAS_LITELLM = True
except Exception as _e:                  # پکیج نصب نیست → فقط مترجم ساده کار می‌کند
    _HAS_LITELLM = False
    log.error("litellm نصب نیست (%s) — pip install litellm", _e)


def _env_int(name, default):
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


COOLDOWN_SECONDS = _env_int("LLM_COOLDOWN_SECONDS", 180)
NUM_RETRIES = _env_int("LLM_NUM_RETRIES", 1)
ALLOWED_FAILS = _env_int("LLM_ALLOWED_FAILS", 2)
JSON_MODE = (os.getenv("TRANSLATE_JSON_MODE", "false").strip().lower()
             in ("1", "true", "yes", "on"))
MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 4000)
# افزودن /no_think به انتهای پرامپت — در خانواده Qwen3 تفکر را خاموش می‌کند
NO_THINK_SUFFIX = (os.getenv("TRANSLATE_NO_THINK_SUFFIX", "false").strip().lower()
                   in ("1", "true", "yes", "on"))
DEBUG_RAW = (os.getenv("TRANSLATE_DEBUG", "false").strip().lower()
             in ("1", "true", "yes", "on"))

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
        + ("\n/no_think" if NO_THINK_SUFFIX else "")
    )


def _repair_json(s):
    """ترمیم JSON نیمه‌کاره‌ای که وسط جمله قطع شده (سقف توکن پر شده)."""
    s = s.rstrip()
    in_str, esc, depth = False, False, 0
    for ch in s:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    if in_str:
        s += '"'
    s = re.sub(r",\s*$", "", s)
    if depth > 0:
        s += "}" * depth
    return s


def _extract_json(text):
    text = (text or "").strip()
    # مدل‌های reasoning گاهی اول بلندبلند فکر می‌کنند
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"<think>.*$", "", text, flags=re.S | re.I)
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()

    start = text.find("{")
    if start == -1:
        return None
    cand = text[start:]
    end = cand.rfind("}")
    whole = cand[: end + 1] if end != -1 else cand

    for attempt in (whole, whole.replace("\n", " "), _repair_json(cand)):
        try:
            data = json.loads(attempt)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


def _msg_text(resp):
    """متن جواب؛ اگر content خالی بود سراغ reasoning_content می‌رویم."""
    msg = resp.choices[0].message
    txt = (getattr(msg, "content", None) or "").strip()
    if not txt:
        txt = (getattr(msg, "reasoning_content", None) or "").strip()
    return txt


# از این سقف رد نمی‌شویم — کپشن عکس در تلگرام ۱۰۲۴ کاراکتر است
BODY_LIMIT = 820


def _trim(text, limit=BODY_LIMIT):
    """کوتاه کردن متن بدون بریدن وسط کلمه یا جمله."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text

    head = text[:limit]
    best = -1
    for mark in (".", "\u061f", "!", "\u060c\n", "\n", "\u00bb"):
        best = max(best, head.rfind(mark))
    if best > limit * 0.5:
        return head[: best + 1].strip()

    sp = head.rfind(" ")
    if sp > 0:
        head = head[:sp]
    return head.strip() + "\u2026"


HIGH_SIGNALS = (
    "here we go", "official", "confirmed", "medical", "release clause",
    "agreement", "agreed", "signs", "signed", "injury", "ruled out",
    "exclusive", "breaking",
)


def _fix_importance(item, data):
    """مدل‌های کوچک خبر فوری را normal می‌زنند؛ خودمان دوباره قضاوت م��‌کنیم."""
    if data.get("importance") == "high":
        return
    if item.get("priority"):
        data["importance"] = "high"
        return
    blob = ((item.get("title") or "") + " " + (item.get("body") or "")).lower()
    if any(s in blob for s in HIGH_SIGNALS):
        data["importance"] = "high"


# ---------------- مترجم ساده (بدون کلید) ----------------
def _apply_glossary(text):
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
        chunks = [body[i:i + 4500] for i in range(0, min(len(body), 9000), 4500)]
        fa_body = _apply_glossary(" ".join(tr.translate(c) for c in chunks))

    if not fa_body and not fa_title:
        raise RuntimeError("خروجی خالی")

    return {
        "title": fa_title,
        "body": _trim(fa_body or fa_title),
        "importance": "high" if item.get("priority") else "normal",
        "tags": [],
        "machine": True,
    }


# ---------------- ساخت زنجیره برای LiteLLM ----------------
def _deployments():
    """از TRANSLATE_ORDER یک model_list برای Router می‌سازد.

    خروجی: (deployments, names, plain_enabled)
    """
    deployments, names, plain = [], [], False

    for raw in config.TRANSLATE_ORDER:
        slot = raw.strip().lower()

        if slot in ("translate", "translator", "deep_translator", "google"):
            if config.ENABLE_DEEP_TRANSLATOR:
                plain = True
            continue

        if slot == "gemini":
            for i, k in enumerate(config.GEMINI_API_KEYS):
                name = "gemini/" + config.GEMINI_MODEL + (f"#{i+1}" if i else "")
                deployments.append({
                    "model_name": name,
                    "litellm_params": {
                        "model": "gemini/" + config.GEMINI_MODEL,
                        "api_key": k,
                        "timeout": config.REQUEST_TIMEOUT,
                    },
                    "model_info": {"id": name},
                })
                names.append(name)
            continue

        cfg = config.LLM_SLOTS.get(slot)
        if not cfg or not cfg["key"] or not cfg["base_url"] or not cfg["model"]:
            continue

        name = cfg["name"] or slot
        # خاموش‌کردن حالت تفکر برای این اسلات:  LLM7_NOTHINK=true
        nothink = (os.getenv(slot.upper() + "_NOTHINK", "").strip().lower()
                   in ("1", "true", "yes", "on"))
        # تایم‌اوت جداگانه برای این اسلات:  LLM1_TIMEOUT=60
        timeout = _env_int(slot.upper() + "_TIMEOUT", config.REQUEST_TIMEOUT)
        host = cfg["base_url"].lower()
        params = {
            # پیشوند openai/ یعنی «این اندپوینت سازگار با OpenAI است»
            "model": "openai/" + cfg["model"],
            "api_base": cfg["base_url"].rstrip("/"),
            "api_key": cfg["key"],
            "timeout": timeout,
        }
        if "openrouter" in cfg["base_url"]:
            params["extra_headers"] = {
                "HTTP-Referer": "https://t.me/LiverpooliRani",
                "X-Title": "LFC News Bot",
            }
        if nothink:
            # هر سرویس زبان خودش را دارد؛ همه‌چی از extra_body می‌رود تا درست عین همان JSON خام فرستاده شود
            # (اگر top-level بفرستیم، litellm/مسیرهای SDK ممکنه قبل ارسال حذفش کنند)
            if "openrouter" in host:
                params["extra_body"] = {
                    "reasoning": {"enabled": False, "exclude": True}
                }
            elif "groq.com" in host:
                # qwen/qwen3.6-27b روی گروک: فقط none/default مجاز است؛ hidden یعنی اصلاً تگ فکر برنگردد
                params["extra_body"] = {
                    "reasoning_effort": "none",
                    "reasoning_format": "hidden",
                }
            elif "googleapis.com" in host:
                params["extra_body"] = {"reasoning_effort": "none"}
            elif not any(h in host for h in ("cerebras.ai", "mistral.ai")):
                # سرورهای vLLM-مانند (مثل opencode) این را می‌فهمند
                params["extra_body"] = {
                    "chat_template_kwargs": {"enable_thinking": False}
                }
        deployments.append({
            "model_name": name,
            "litellm_params": params,
            "model_info": {"id": name},
        })
        names.append(name)

        # کلید بکاپ (مثلاً برای qwen وقتی سقف روزانه خورد):  LLM<n>_KEY_BACKUP
        # یک دپلویمنت جدا با همین مدل ولی کلید دوم ساخته می‌شود — litellm وقتی
        # کلید اصلی rate-limit شود خودکار به این سوییچ می‌کند.
        backup_key = cfg.get("key_backup") or ""
        if backup_key and backup_key != cfg["key"]:
            bk_params = dict(params)
            bk_params["api_key"] = backup_key
            bk_name = name + "#2"
            deployments.append({
                "model_name": bk_name,
                "litellm_params": bk_params,
                "model_info": {"id": bk_name},
            })
            names.append(bk_name)

    return deployments, names, plain


_router = None
_router_names = []


def _get_router():
    """Router یک بار ساخته می‌شود تا حافظه‌ی cooldown بین خبرها حفظ شود."""
    global _router, _router_names
    if _router is not None:
        return _router, _router_names
    if not _HAS_LITELLM:
        return None, []

    deployments, names, _ = _deployments()
    if not deployments:
        return None, []

    # هر مدل، بقیه‌ی زنجیره را به‌عنوان جایگزین خودش دارد
    fallbacks = [{names[i]: names[i + 1:]} for i in range(len(names) - 1)]

    _router = Router(
        model_list=deployments,
        fallbacks=fallbacks,
        num_retries=NUM_RETRIES,
        retry_after=2,
        allowed_fails=ALLOWED_FAILS,
        cooldown_time=COOLDOWN_SECONDS,
        routing_strategy="simple-shuffle",
        set_verbose=False,
    )
    _router_names = names
    log.info("زنجیره LiteLLM آماده شد: %s", " → ".join(names))
    return _router, names


def _single_call(dep, prompt):
    """صدا زدن مستقیم یک مدل بدون Router — برای doctor و benchmark."""
    if not _HAS_LITELLM:
        raise RuntimeError("litellm نصب نیست: pip install litellm")
    params = dict(dep["litellm_params"])
    if JSON_MODE:
        params.setdefault("response_format", {"type": "json_object"})
    resp = litellm.completion(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=MAX_TOKENS,
        **params,
    )
    txt = _msg_text(resp)
    if DEBUG_RAW or not _extract_json(txt):
        log.warning("[%s] خروجی خام: %s", dep["model_name"],
                    (txt or "(خالی)")[:400].replace("\n", " "))
    return txt


def _chain():
    """��ازگاری با doctor.py و benchmark.py.

    خروجی: لیست (نام، نوع، تابع) دقیقاً مثل نسخه قبلی.
    هر تابع فقط همان یک مدل را می‌زند، بدون fallback — تا تست تک‌تک مدل‌ها درست باشد.
    """
    deployments, _, plain = _deployments()
    out = [
        (d["model_name"], "llm", (lambda p, d=d: _single_call(d, p)))
        for d in deployments
    ]
    if plain:
        out.append(("مترجم گوگل", "plain", _deep_translate))
    return out


def chain_names():
    """فقط برای لاگ، /health و doctor."""
    _, names, plain = _deployments()
    return names + (["مترجم گوگل"] if plain else [])


def _provider_of(resp, default):
    """کدام مدل واقعاً جواب داد."""
    try:
        pid = (getattr(resp, "_hidden_params", {}) or {}).get("model_id")
        if pid:
            return str(pid)
    except Exception:
        pass
    return str(getattr(resp, "model", "") or default)


# ---------------- ورودی اصلی ----------------
def translate(item):
    """خروجی: dict با کلیدهای title / body / importance / tags / provider یا None."""
    router, names = _get_router()
    _, _, plain_enabled = _deployments()
    prompt = _build_prompt(item)
    errors = []

    if router and names:
        kwargs = {
            "model": names[0],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": MAX_TOKENS,
        }
        if JSON_MODE:
            kwargs["response_format"] = {"type": "json_object"}

        t0 = time.time()
        try:
            resp = router.completion(**kwargs)
            text = _msg_text(resp)
            provider = _provider_of(resp, names[0])
            data = _extract_json(text)

            if data and data.get("body"):
                health.record_ok(provider, ms=(time.time() - t0) * 1000)
                health.record_counter("translated")
                if provider != names[0]:
                    health.record_counter("fallback_used")
                    log.info("ترجمه با سرویس جایگزین انجام شد: %s", provider)
                data.setdefault("title", item.get("title", ""))
                data.setdefault("importance", "normal")
                data.setdefault("tags", [])
                data["body"] = _trim(str(data["body"]))
                data["title"] = str(data["title"]).strip()[:120]
                _fix_importance(item, data)
                data["provider"] = provider
                return data

            health.record_fail(provider, "خروجی نامعتبر (JSON خراب یا خالی)")
            errors.append(f"{provider}: خروجی نامعتبر")
            log.warning("%s: خروجی نامعتبر | خام: %s", provider,
                        (text or "(خالی)")[:400].replace("\n", " "))
        except Exception as e:
            health.record_fail(names[0], e)
            errors.append(f"زنجیره LLM: {e}")
            log.warning("کل زنجیره LLM شکست خورد | %s", e)

    # آخرین سنگر: مترجم ماشینی بدون کلید
    if plain_enabled:
        t0 = time.time()
        try:
            data = _deep_translate(item)
            health.record_ok("مترجم گوگل", ms=(time.time() - t0) * 1000)
            health.record_counter("translated")
            health.record_counter("machine_used")
            _fix_importance(item, data)
            data["provider"] = "مترجم گوگل"
            return data
        except Exception as e:
            health.record_fail("مترجم گوگل", e)
            errors.append(f"مترجم گوگل: {e}")

    health.record_counter("chain_failed")
    log.error("هیچ سرویس ترجمه‌ای کار نکرد:")
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
