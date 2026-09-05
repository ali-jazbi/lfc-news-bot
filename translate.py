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
    log.error("litellm not installed (%s) — pip install litellm", _e)


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
MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 8000)
# این سقف فقط برای سازگاری/تست است؛ مقاله‌ی طولانی با chunk ترجمه می‌شود.
INPUT_BODY_LIMIT = _env_int("LLM_INPUT_BODY_LIMIT", 12000)
ARTICLE_CHUNK_CHARS = _env_int("LLM_ARTICLE_CHUNK_CHARS", 5000)
# افزودن /no_think به انتهای پرامپت — در خانواده Qwen3 تفکر را خاموش می‌کند
NO_THINK_SUFFIX = (os.getenv("TRANSLATE_NO_THINK_SUFFIX", "false").strip().lower()
                   in ("1", "true", "yes", "on"))
DEBUG_RAW = (os.getenv("TRANSLATE_DEBUG", "false").strip().lower()
             in ("1", "true", "yes", "on"))

SYSTEM_PROMPT = """تو مترجم و خبرنگار حرفه‌ای فوتبال هستی که برای کانال هواداران لیورپول در تلگرام می‌نویسی.

قواعد:
1. خبر  را به فارسی روان، خبری و طبیعی برگردان. ترجمه تحت‌اللفظی ممنوع است.

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
1-ج. اگر متن ورودی یک توییت نقل‌قول‌شده (کووت / [نقل‌قول از ...]) است:
   - حتماً و بدون استثنا هر دو بخش را با هم ترجمه کن: هم واکنش/نظر توییت‌کننده و هم جزئیات توییت نقل‌قول‌شده (مبالغ، نام بازیکن، ادعای اصلی).
   - هرگز متن توییت کوت‌شده را نادیده نگیر یا حذف نکن؛ زیرا اصل خبر و ارقام در آن قرار دارد.
   - مثال: اگر متن باشد «Looking very likely... 🎯 \n\n [نقل‌قول از @AnfieldSector]: Sweet spot: €130m-€140m... 🧘‍♂️🇫🇷»،
     ترجمه بدنه باید بشود: «به نظر می‌رسد احتمال وقوع این انتقال بسیار زیاد است. مبلغ ایده‌آل: بین ۱۳۰ تا ۱۴۰ میلیون یورو برآورد شده است. 🎯🇫🇷»
2. اسامی خاص (بازیکن، باشگاه، ورزشگاه) را ترجمه نکن؛ فقط به فارسی آوانگاری کن و از فهرست واژگان زیر پیروی کن.

2-الف. افراد مهمِ لیورپول را اشتباه نگیر:
   - سرمربی کنونی لیورپول «آندونی ایرائولا» (Andoni Iraola) است — هرگز او را «اسلوت» (Slot) صدا نزن.
   - آرنه اسلوت (Arne Slot) سرمربی سابق است؛ اگر متن درباره او بود بگو «آرنه اسلوت».
   - هر جا نام «Iraola» دیدی، آوانگاری کن: «ایرائولا».

3. لحن: رسمی ولی صمیمی، مثل کانال‌های خبری فوتبال. از اغراق و نظر شخصی پرهیز کن.
4. اعداد، مبالغ، تاریخ‌ها و نقل‌قول‌ها را دقیق نگه دار. چیزی از خودت اضافه نکن.
5. مقاله‌ها و گزارش‌های طولانی را کامل ترجمه کن — همه‌ی پاراگراف‌ها، نقل‌قول‌ها و جزئیات را بیاور؛ فقط تکرار و حاشیه را می‌توانی فشرده کنی. خلاصه‌کردن به چند جمله ممنوع است. برای توییت‌های کوتاه و نقل‌قول‌ها، ترجمه را دقیق، مستقیم و بدون کش‌دادن یا جملات ساختگی بنویس.
5-الف. اگر متن کوتاه است (توییت‌های معمولی زیر ~۲۴۰ کاراکتر)، حتماً یک عنوان کوتاه و خبری در فیلد title بنویس؛
   اما عنوان و بدنه نباید یکسان یا تکرار یکدیگر باشند. عنوان باید خلاصه/زاویه‌ی خبری مستقل داشته باشد و بدنه فقط
   ترجمه‌ی متن اصلی را بیاورد. اگر متن اصلی خودش یک جمله‌ی کامل و تیترمانند است، می‌توانی همان ترجمه را در title
   بگذاری، ولی در این حالت body را دوباره با همان جمله تکرار نکن.
5-ب. برای پست‌های کوتاهِ نقل‌قولی یا واکنشی، title را به شکل یک تیتر مستقل بنویس (مثلاً «ستایش ایرائولا از هوش مک‌آلیستر»)
   و در body فقط محتوای نقل‌قول/متن اصلی را یک بار بیاور. گوینده را در title معرفی نکن اگر باعث می‌شود همان جمله‌ی نقل‌شده
   در body دوباره تکرار شود؛ از نوشتن دو نسخه‌ی هم‌مضمون، مثل «ایرائولا: ...» و سپس همان «...»، جداً خودداری کن.
   تیتر بازنویسی‌شده فقط برای مقاله‌ها و توییت‌های بلند لازم نیست؛ برای خبر کوتاه هم وقتی عنوانی مستقل از بدنه می‌سازی، آن را حفظ کن.
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
12. اگر در متن اصلی خطی فقط یک مارکر تصویر مثل [IMG-0] یا [IMG-1] بود، آن را عیناً و بدون هیچ تغییری در همان جای متن خروجی نگه دار — این‌ها جای عکس‌های مقاله را نشان می‌دهند.
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
        f"متن اصلی:\n{item.get('body') or ''}\n---\nخروجی JSON:"
        + ("\n/no_think" if NO_THINK_SUFFIX else "")
    )


def _split_article(text, limit=ARTICLE_CHUNK_CHARS):
    """مقاله را در مرز پاراگراف/جمله می‌شکند، نه وسط متن."""
    text = (text or '').strip()
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(". ", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


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


# الگوهای خطای سرور و پاسخ‌های نامعتبر وب
ERROR_SIGNATURES = (
    "error 500",
    "500.that’s an error",
    "500.that's an error",
    "that’s all we know",
    "that's all we know",
    "there was an error",
    "please try again later",
    "server error",
    "rate limit",
    "too many requests",
    "429 too many",
    "unusual traffic",
    "enable javascript",
    "just a moment",
    "cloudflare",
    "response id:",
    "request id:",
    "<!doctype",
    "<html",
    "<body",
)


def contains_error_signature(text):
    """آیا متن حاوی امضاهای خطای وب، سرور یا پاسخ‌های نامعتبر است؟"""
    if not text:
        return False
    low = text.lower()
    return any(sig in low for sig in ERROR_SIGNATURES)


def is_valid_persian_translation(text, min_persian_chars=2):
    """آیا متن ورودی یک ترجمه فارسی معتبر است (نه پیام خطای /HTML)؟"""
    if not text or not isinstance(text, str):
        return False
    if contains_error_signature(text):
        return False
    persian_chars = len(re.findall(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]", text))
    if persian_chars < min_persian_chars:
        return False
    return True


def _looks_like_valid_translation(text):
    """مرزی برای ردکردن خروجی‌های قاطی و تکه‌تکه‌ی qwen؛ فقط روی متن ترجمه اعمال می‌شود."""
    if not text or not isinstance(text, str):
        return False
    text = text.strip()
    if not text or contains_error_signature(text):
        return False

    if re.search(r"\*\*|__|##|\|\|\|", text):
        return False

    clean = re.sub(r"[*_`~#\[\]{}()<>|]", " ", text)
    clean = clean.replace("‌", "").replace("\u200c", "").replace("\u200d", "")
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return False

    if not is_valid_persian_translation(clean, min_persian_chars=6):
        return False

    symbol_chars = sum(
        1 for ch in clean
        if not (ch.isalnum() or ch in " \n\t\u0600-\u06FF،؛:.!?%/()[]-\"'")
    )
    # اموجی‌ها، آستریک‌ها و مارک‌داون‌های اضافی در خروجی خراب زیادند؛ ترجمه معتبر معمولاً در این حد نیست.
    if symbol_chars > max(6, len(clean) * 0.12):
        return False

    words = re.split(r"[\s،؛:.!?]+", clean)
    words = [w for w in words if w and re.search(r"[\u0600-\u06FF]", w)]
    if len(words) < 3:
        return False

    common = {
        "لیورپول", "باشگاه", "بازیکن", "مربی", "توافق", "انتقال", "پوند",
        "یورو", "مبلغ", "هفته", "بازی", "بازگشت", "مصدومیت", "تیم", "خبر",
        "فصل", "گزارش", "مذاکره", "دور", "میلیون", "گل", "تعویض", "نقل", "نقل‌وانتقالات",
        "قهرمانان", "داور", "سطح", "علیه", "قبل", "دارد", "می‌شود", "شد",
        "می‌کند", "این", "آن", "چنین", "برای", "از", "در", "به", "و", "که",
    }
    hits = sum(1 for w in words if w.lower() in common or "لیورپ" in w or "باشگاه" in w or "تیم" in w)
    if hits == 0:
        return False

    broken = sum(1 for w in words if len(w) > 18)
    if broken >= max(2, len(words) // 5):
        return False

    # متن درهم‌ریخته (دو نسخه‌ی موازی که کلمه‌به‌کلمه در هم تنیده شده‌اند) را رد کن.
    # در ترجمه سالم، شِنگل‌های ۵کلمه‌ای تقریباً تکرار نمی‌شوند؛ در خروجی خرابِ qwen
    # که دو رشته را با هم قاطی کرده، نسبت تکرار بالاست.
    if len(words) >= 40:
        n = 5
        shingles = [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]
        if shingles:
            uniq = len(set(shingles))
            if uniq / len(shingles) < 0.88:
                return False

    # اثر انگشت JSON خراب‌شده: «\n» هایی که بک‌اسلششان گم شده و به حرف n تکی
    # تبدیل شده‌اند (در.nاصلی ، اجراnشد ، nاین). حرف لاتینِ تنها — نه بخشی از
    # سرواژه‌ای مثل VAR یا PSG — در متن فارسی سالم هرگز مجاز نیست.
    lone_latin = re.findall(r"(?<![a-zA-Z])[a-zA-Z](?![a-zA-Z])", clean)
    if len(lone_latin) >= 2:
        return False

    return True


def _strip_hashtags(text):
    """حذف هشتگ‌ها از خروجی نهایی ترجمه (تنها روی خروجی، نه روی ورودی).

    - `#…` (لاتین و فارسی/یونیکد) را حذف می‌کند — فقط آن‌هایی که بعدشان کلمه است.
    - artifact خروجی گوگل/مدل‌ها (`\x3C` که شکل escape شده‌ی `<` است) را پاک می‌کند.
    - فاصله‌های اضافی را فشرده می‌کند.
    - هیچ تغییری در متنِ ِ اصلی/ورودی نمی‌دهد — پس تشخیص relevance (مثل #LFC)
      دست‌نخورده می‌ماند.
    """
    if not text:
        return text or ""
    out = re.sub(r"#[\w\u0600-\u06FF][\w\u0600-\u06FF\-_]*", " ", text)
    # پاک‌سازی escape شده‌ی < (artifact مترجم گوگل) به شکل‌های \x3C / \x3c / \\x3c
    out = re.sub(r"\\+x[0-9a-fA-F]{2}", " ", out)
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    return out


def _balanced_json(text):
    """اولین ابجکت { ... } متوازن را برمی‌دارد (حساب رشته‌ها هم می‌شود).

    مسیر پشتیبان برای وقتی که بعد از JSON خروجی اختلال‌دار با آکولاد اضافه می‌شود —
    rfind در این حالت به تودر درست ختم نمی‌رسد.
    """
    start = text.find("{")
    if start == -1:
        return None


# end of translation module
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


# end of translation module


def _parse_junk_string(rest):
    """خروجی خراب را به یک string ساده می‌خواند؛ به اولین کوتیشن معتبر می‌رسد."""
    rest = rest.lstrip()
    start = rest.find('"')
    if start == -1:
        return None


# end of translation module
    out = []
    esc = False
    for ch in rest[start + 1:]:
        if esc:
            out.append(ch)
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            return "".join(out)
        out.append(ch)
    return None


# end of translation module


def _parse_junk_scalar(rest):
    """بلوک ساده‌ی غیر-string را تا اولین comma/brace/bracket می‌خواند."""
    rest = rest.lstrip()
    if not rest:
        return None


# end of translation module
    stop = len(rest)
    for i, ch in enumerate(rest):
        if ch in ",}]":
            stop = i
            break
    token = rest[:stop].strip()
    if not token:
        return None


# end of translation module
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1]
    if token in ("true", "false"):
        return token == "true"
    if token.lower() in ("null", "none"):
        return None


# end of translation module
    return token.strip('"')


def _parse_junk_array(rest):
    """لیست خراب را تا اولین ] مناسب می‌خواند و در صورت نبود JSON، برمی‌گرداند."""
    rest = rest.lstrip()
    if not rest.startswith('['):
        return None


# end of translation module
    depth = 0
    in_str = False
    esc = False
    end = None
    for i, ch in enumerate(rest):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return None


# end of translation module
    candidate = rest[:end + 1]
    try:
        data = json.loads(candidate)
        if isinstance(data, list):
            return data
    except Exception:
        pass

    items = []
    blob = candidate[1:-1]
    for part in re.split(r',\s*(?=(?:[^"]*"[^"]*")*[^"]*$)', blob):
        p = part.strip()
        if not p:
            continue
        p = p.strip().strip('"')
        if p:
            items.append(p)
    return items if items else None


def _salvage_json_object(text):
    """برای خروجی‌های مخرب qwen: keyهای title/body/importance/tags را حتی در صورت junk پیدا می‌کند."""
    s = (text or "").strip()
    if not s:
        return None


# end of translation module

    out = {}
    key_order = ("title", "body", "importance", "tags")
    for key in key_order:
        pos = -1
        for match in re.finditer(re.escape(key), s, flags=re.I):
            pos = match.start()
        if pos == -1:
            continue
        col = s.find(":", pos)
        if col == -1:
            continue
        rest = s[col + 1:]
        val = None
        if rest.lstrip().startswith('"'):
            val = _parse_junk_string(rest)
        elif rest.lstrip().startswith('['):
            val = _parse_junk_array(rest)
        else:
            val = _parse_junk_scalar(rest)
        if val is not None:
            out[key] = val

    if not out:
        return None


# end of translation module
    out.setdefault("title", "")
    out.setdefault("body", "")
    out.setdefault("importance", "normal")
    out.setdefault("tags", [])
    return out


def _extract_json(text):
    text = (text or "").strip()
    # مدل‌های reasoning گاهی اول بلندبلند فکر می‌کنند
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"<think>.*$", "", text, flags=re.S | re.I)
    text = re.sub(r"<details>.*?</details>", "", text, flags=re.S | re.I)
    # بعضی مدل‌ها (مثل qwen عبر opencode) بعد از JSON یک کامنت HTML متاداتا می‌دهند —
    # آکولادِ داخل آن rfind("}") را گول می‌زند و JSON سالم رد می‌شود.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()

    start = text.find("{")
    if start == -1:
        return None


# end of translation module
    cand = text[start:]
    end = cand.rfind("}")
    whole = cand[: end + 1] if end != -1 else cand

    for attempt in (whole, whole.replace("\n", " "),
                    _balanced_json(cand), _repair_json(cand)):
        try:
            data = json.loads(attempt)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    salvage = _salvage_json_object(cand)
    if salvage and isinstance(salvage, dict):
        return salvage
    return None


# end of translation module


def _msg_text(resp):
    """متن جواب؛ اگر content خالی بود سراغ reasoning_content می‌رویم."""
    msg = resp.choices[0].message
    txt = (getattr(msg, "content", None) or "").strip()
    if not txt:
        txt = (getattr(msg, "reasoning_content", None) or "").strip()
    return txt


# سقف کپشن تلگرام — فقط برای پیام تلگرام کاربرد دارد، نه برای صفحه‌ی Telegraph
CAPTION_LIMIT = 820


def _trim(text, limit=CAPTION_LIMIT):
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

    fa_title = ""
    if title:
        raw_fa_title = tr.translate(title[:900])
        if raw_fa_title and is_valid_persian_translation(raw_fa_title, min_persian_chars=1):
            fa_title = _strip_hashtags(_apply_glossary(raw_fa_title))
        elif raw_fa_title and contains_error_signature(raw_fa_title):
            raise RuntimeError(f"خطای وب سرور در ترجمه عنوان: {raw_fa_title[:60]}")

    fa_body = ""
    if body:
        chunks = [body[i:i + 4500] for i in range(0, min(len(body), 9000), 4500)]
        translated_chunks = []
        for c in chunks:
            raw_c = tr.translate(c)
            if not raw_c or contains_error_signature(raw_c):
                raise RuntimeError(f"خطای مترجم گوگل در ترجمه متن: {raw_c[:60] if raw_c else 'خالی'}")
            translated_chunks.append(raw_c)
        fa_body = _strip_hashtags(_apply_glossary(" ".join(translated_chunks)))

    final_body = _trim(fa_body or fa_title)
    if not is_valid_persian_translation(final_body, min_persian_chars=2):
        raise RuntimeError(f"خروجی ترجمه نامعتبر است (فاقد حروف فارسی یا حاوی خطا): {final_body[:80]}")

    return {
        "title": fa_title,
        "body": final_body,
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
    log.info("LiteLLM chain ready: %s", " → ".join(names))
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
        log.warning("[%s] raw output: %s", dep["model_name"],
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
    """خروجی: dict با کلیدهای title / body / importance / tags / provider یا None.

    مقاله‌های طولانی تکه‌تکه ترجمه می‌شوند تا سقف خروجی مدل باعث حذف نیمه‌ی مقاله نشود.
    """
    body = (item.get("body") or "").strip()
    if len(body) > ARTICLE_CHUNK_CHARS:
        return _translate_long_article(item)
    return _translate_short(item)


def _translate_short(item):
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

            if data and data.get("body") and _looks_like_valid_translation(str(data.get("body"))):
                health.record_ok(provider, ms=(time.time() - t0) * 1000)
                health.record_counter("translated")
                if provider != names[0]:
                    health.record_counter("fallback_used")
                    log.info("translated with fallback service: %s", provider)
                data.setdefault("title", item.get("title", ""))
                data.setdefault("importance", "normal")
                data.setdefault("tags", [])
                data["body"] = _strip_hashtags(_apply_glossary(str(data["body"])))
                data["title"] = _strip_hashtags(_apply_glossary(str(data["title"]).strip()))[:120]
                if not _looks_like_valid_translation(str(data["title"])) and data["title"]:
                    data["title"] = ""
                _fix_importance(item, data)
                data["provider"] = provider
                return data

            health.record_fail(provider, "خروجی نامعتبر (JSON خراب، خالی، یا فاقد متن معتبر فارسی)")
            errors.append(f"{provider}: خروجی نامعتبر")
            log.warning("%s: invalid output | raw: %s", provider,
                        (text or "(خالی)")[:400].replace("\n", " "))
        except Exception as e:
            health.record_fail(names[0], e)
            errors.append(f"زنجیره LLM: {e}")
            log.warning("full LLM chain failed | %s", e)

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
    log.error("no translation service worked:")
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


# end of translation module
