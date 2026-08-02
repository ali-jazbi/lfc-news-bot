"""پیکربندی مرکزی - همه چیز از فایل .env خوانده می‌شود."""
import os
import json
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

BASE_DIR = Path(__file__).parent


def _get(key, default=""):
    return os.environ.get(key, default).strip()


def _int(key, default):
    try:
        return int(_get(key, str(default)))
    except ValueError:
        return default


def _float(key, default):
    try:
        return float(_get(key, str(default)))
    except ValueError:
        return default


def _list(key, default=""):
    raw = _get(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


# --- Telegram ---
BOT_TOKEN = _get("BOT_TOKEN")
ADMIN_CHAT_ID = _get("ADMIN_CHAT_ID")          # گروه ادمین‌ها (پیش‌نمایش)
CHANNEL_ID = _get("CHANNEL_ID")                # فقط در حالت auto لازم است
CHANNEL_USERNAME = _get("CHANNEL_USERNAME", "@LiverpooliRani")
PROXY = _get("PROXY")                          # مثال: socks5h://127.0.0.1:1080

# آیدی عددی کاربرانی که اجازه دارند دستور/دکمه بزنند (با کاما جدا کن).
# خالی = همه‌ی اعضای گروه ادمین اجازه دارند (رفتار قدیم، برای سازگاری).
# آیدی عددی خودت را با /id در همان گروه می‌گیری.
ADMIN_USER_IDS = [int(x) for x in _list("ADMIN_USER_IDS") if x.lstrip("-").isdigit()]

# manual = ربات فقط نسخه آماده را در همان گروه می‌دهد (انتشار دستی توسط ادمین)
# auto   = ربات خودش روی CHANNEL_ID می‌فرستد
PUBLISH_MODE = _get("PUBLISH_MODE", "manual").lower()
if PUBLISH_MODE not in ("manual", "auto"):
    PUBLISH_MODE = "manual"
if PUBLISH_MODE == "auto" and not CHANNEL_ID:
    PUBLISH_MODE = "manual"

# --- منابع ---
LFC_NEWS_URL = _get("LFC_NEWS_URL", "https://www.liverpoolfc.com/news")
ENABLE_LFC = _get("ENABLE_LFC", "true").lower() == "true"
ENABLE_ROMANO = _get("ENABLE_ROMANO", "true").lower() == "true"
ENABLE_TWITTER = _get("ENABLE_TWITTER", "true").lower() == "true"

# لایه یک برداشت توییت — مستقیم از سرور خود توییتر (بدون آینه).
# تست واقعی نشان داد این endpoint فعلاً همیشه HTTP 200 با بدنه کاملاً خالی
# برمی‌گرداند (یعنی توییتر بی‌سروصدا بلاکش کرده)، پس پیش‌فرض خاموشه تا وقتی
# روزی دوباره درست شد روشنش کنیم. کدش همچنان هست و فقط با یک true در .env فعال می‌شود.
ENABLE_TWITTER_SYNDICATION = (
    _get("ENABLE_TWITTER_SYNDICATION", "false").lower() == "true"
)

# فیدهای RSS رسمی خبرگزاری‌ها — رسمی و پایدار، هیچ وابستگی به آینه/میرور ندارد.
# برای افزودن فید جدید کافی است آدرسش را اینجا اضافه کنی (با کاما جدا کن).
ENABLE_OUTLET_RSS = _get("ENABLE_OUTLET_RSS", "true").lower() == "true"
OUTLET_RSS_FEEDS = _list(
    "OUTLET_RSS_FEEDS",
    "https://feeds.bbci.co.uk/sport/football/teams/liverpool/rss.xml",
)

# بلواسکای — جایگزین رسمی نیتر برای خبرنگارانی که آنجا هم پست می‌گذارند.
# غیرفعال است تا وقتی BLUESKY_HANDLES پر شود (نمونه: someone.bsky.social)
ENABLE_BLUESKY = _get("ENABLE_BLUESKY", "false").lower() == "true"
BLUESKY_HANDLES = _list("BLUESKY_HANDLES", "")

# --- حساب‌های توییتر ---
# آینه‌هایی که توییتر را به RSS تبدیل می‌کنند (اولین زنده انتخاب می‌شود)
NITTER_BASES = _list(
    "NITTER_BASES",
    "https://nitter.net,"
    "https://lightbrd.com,"
    "https://xcancel.com,"
    "https://nitter.tiekoetter.com,"
    "https://nitter.space,"
    "https://rsshub.rssforever.com/twitter/user,"
    # کاندیدهای جدید — تست‌نشده‌اند از اینجا؛ با اجرای test_twitter_sources.py
    # روی اینترنت واقعی مشخص می‌شود کدام زنده‌اند — مرده‌ها خودکار backoff می‌خورند
    "https://nitter.poast.org,"
    "https://nitter.privacyredirect.com,"
    "https://nitter.d420.de",
)

# درجه‌یک: هر سیکل چک می‌شوند (خبرشکن‌های اصلی)
TWITTER_TIER1 = _list(
    "TWITTER_TIER1",
    "FabrizioRomano,David_Ornstein,JamesPearceLFC,DavidLynchLFC,_pauljoyce,LFC",
)

# بقیه حساب‌ها — به نوبت و چرخشی خوانده می‌شوند
TWITTER_ACCOUNTS = _list(
    "TWITTER_ACCOUNTS",
    "FabrizioRomano,David_Ornstein,JamesPearceLFC,DavidLynchLFC,_pauljoyce,LFC,"
    "NicoSchira,DiMarzio,TheAthleticFC,JacobsBen,LewisSteele_,_ChrisBascombe,"
    "MelissaReddy_,ptgorst,Plettigoal,OptaAnalyst,PhysioScout,FMeetsData,"
    "DataAnalyticEPL,NextGenSector,AnfieldSector,anfieldsociaI,Anfieldmedia_,"
    "LiverpoolFF,Asim_LFC,SajadIqballfc,Waleed_Alramahi,PartedBeard,mnstr_mntlt",
)

# حساب‌های مختص لیورپول — فیلتر کلمه‌ای رویشان اعمال نمی‌شود
# فقط حساب‌های ۱۰۰٪ لیورپولی؛ خبرنگاران عمداً در این لیست نیستند
# چون خبر فوتبال جهان هم می‌دهند (مثلاً خبر فیفا از پل جویس)
TWITTER_LFC_ONLY = _list(
    "TWITTER_LFC_ONLY",
    "LFC,AnfieldSector,anfieldsociaI,Anfieldmedia_,LiverpoolFF,"
    "Asim_LFC,SajadIqballfc",
)

# در هر سیکل چند حساب غیردرجه‌یک خوانده شود (بقیه سیکل بعد)
ACCOUNTS_PER_CYCLE = _int("ACCOUNTS_PER_CYCLE", 6)

# توییت کوتاه مثل «Mighty Red making an appearance» خبر نیست
TWEET_MIN_CHARS = _int("TWEET_MIN_CHARS", 60)
TWEET_MIN_WORDS = _int("TWEET_MIN_WORDS", 8)

# توییت قدیمی‌تر از این (ساعت) خبر حساب نمی‌شود — ۰ یعنی بی‌خیال تاریخ
TWEET_MAX_AGE_HOURS = _int("TWEET_MAX_AGE_HOURS", 24)

# --- رسانه‌های توییتر ---
# استخراج همه عکس‌های خودِ توییت (آلبوم) + ویدیو از طریق API بدون کلید
ENABLE_TWITTER_MEDIA = _get("ENABLE_TWITTER_MEDIA", "true").lower() == "true"
ENABLE_TWITTER_VIDEO = _get("ENABLE_TWITTER_VIDEO", "true").lower() == "true"
TWITTER_ALBUM_MAX = _int("TWITTER_ALBUM_MAX", 10)      # سقف آلبوم تلگرام = ۱۰
TWITTER_ENRICH_TTL = _int("TWITTER_ENRICH_TTL", 900)    # کش رسانه، ۱۵ دقیقه

# --- پالایش نرخ درخواست نیتر (جلوگیری از 429) ---
TWITTER_WORKERS = _int("TWITTER_WORKERS", 4)            # بود ۸
TWITTER_INTER_ACCOUNT_DELAY = _float("TWITTER_INTER_ACCOUNT_DELAY", 0.25)
TWITTER_ACCOUNT_SKIP_SECONDS = _int("TWITTER_ACCOUNT_SKIP_SECONDS", 60)  # بود ۱۸۰۰
TWITTER_BASE_SWITCH_THRESHOLD = _float("TWITTER_BASE_SWITCH_THRESHOLD", 0.5)

# فیدهای رومانو - اولین فیدی که جواب بدهد استفاده می‌شود
ROMANO_FEEDS = _list(
    "ROMANO_FEEDS",
    "https://xcancel.com/FabrizioRomano/rss,"
    "https://nitter.net/FabrizioRomano/rss,"
    "https://lightbrd.com/FabrizioRomano/rss,"
    "https://nitter.tiekoetter.com/FabrizioRomano/rss,"
    "https://rsshub.rssforever.com/twitter/user/FabrizioRomano",
)

# اگر هیچ‌کدام از پل‌های بالا جواب نداد، سراغ گوگل نیوز می‌رویم
# (پوشش کمتر و کمی تاخیر، ولی همیشه بالاست)
ROMANO_GOOGLE_FALLBACK = (
    _get("ROMANO_GOOGLE_FALLBACK", "true").lower() == "true"
)
# فقط توییت‌هایی که این کلمات را دارند (برای فن‌پیج لیورپول)
ROMANO_KEYWORDS = _list(
    "ROMANO_KEYWORDS",
    "liverpool,anfield,slot,salah,lfc,reds,merseyside",
)

# خبرهای بی‌ارزش برای کانال — اگر عنوان شامل یکی از این‌ها بود رد می‌شود
SKIP_KEYWORDS = _list(
    "SKIP_KEYWORDS",
    "live gallery,gallery:,photos:,photo gallery,watch:,watch all,in pictures,quiz,"
    "supporters club,we love you liverpool,podcast,competition,"
    "win a,shop,store,ticket info,membership,matchday programme,"
    "lfc tv,subscribe,behind the scenes,foundation,consulate,charity,"
    "soccer clinic,community event",
)

# خبرهای تیم بانوان — اگر کانال پوشششان نمی‌دهد، false بگذار
INCLUDE_WOMEN = _get("INCLUDE_WOMEN", "false").lower() == "true"

# --- نگهبان کانال ---
# قبل از فرستادن به گروه، پست‌های اخیر خود کانال چک می‌شود
# تا خبری که ادمین دیگری دستی گذاشته دوباره پیشنه��د نشود.
CHANNEL_GUARD = _get("CHANNEL_GUARD", "true").lower() == "true"
CHANNEL_GUARD_THRESHOLD = _int("CHANNEL_GUARD_THRESHOLD", 82)  # درصد شباهت
CHANNEL_GUARD_TTL = _int("CHANNEL_GUARD_TTL", 600)             # کش بر حسب ثانیه

# --- زمان‌بندی ---
POLL_INTERVAL = _int("POLL_INTERVAL", 60)      # ثانیه

# سقف انتظار برای پاسخ هر سرویس ترجمه.
# خیلی بلند باشد، یک سرویس هنگ‌کرده کل زنجیره را معطل می‌کند.
REQUEST_TIMEOUT = _int("REQUEST_TIMEOUT", 45)  # ثانیه
MAX_ITEMS_PER_CYCLE = _int("MAX_ITEMS_PER_CYCLE", 5)
BOOTSTRAP_SILENT = _get("BOOTSTRAP_SILENT", "false").lower() == "true"

# --- ترجمه ---
# زنجیره سرویس‌ها به ترتیب اولویت. هر کدام خطا بدهد خودکار می‌رود سراغ بعدی.
# مقادیر مجاز: llm1 تا llm10 ، gemini ، translate
TRANSLATE_ORDER = _list("TRANSLATE_ORDER", "llm1,llm2,llm3,gemini,translate")


def _llm_slot(n):
    """هر سرویسی که API سازگار با OpenAI دارد در یک اسلات جا می‌شود.

    کلید بکاپ (اختیاری):  LLM<n>_KEY_BACKUP
    وقتی کلید اصلی به لیمیت/خطا بخورد، اسلات به کلید بکاپ سوییچ می‌کند —
    مخصوصاً برای سرویس‌های رایگان مثل qwen که سقف روزانه دارند.
    """
    return {
        "name": _get("LLM%d_NAME" % n) or ("llm%d" % n),
        "base_url": _get("LLM%d_BASE_URL" % n),
        "key": _get("LLM%d_KEY" % n),
        "key_backup": _get("LLM%d_KEY_BACKUP" % n),
        "model": _get("LLM%d_MODEL" % n),
    }


LLM_SLOTS = {("llm%d" % n): _llm_slot(n) for n in range(1, 11)}

# مترجم ماشینی گوگل — بدون کلید، بدون سقف. کیفیت پایین‌تر ولی همیشه در دسترس
ENABLE_DEEP_TRANSLATOR = _get("ENABLE_DEEP_TRANSLATOR", "true").lower() == "true"

GEMINI_API_KEYS = _list("GEMINI_API_KEYS")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-2.0-flash")

# --- سایر ---
DB_PATH = _get("DB_PATH", str(BASE_DIR / "data" / "news.db"))
DUPLICATE_THRESHOLD = _int("DUPLICATE_THRESHOLD", 85)

# دامنه فیلتر تکراری:
#   source = فقط درون همان منبع (دو خبرنگار مختلف روی یک موضوع هر دو می‌آیند)
#   global = هر خبر مشابهی از هر منبعی تکراری حساب می‌شود
DUPLICATE_SCOPE = _get("DUPLICATE_SCOPE", "source").lower()
USER_AGENT = _get(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
)

with open(BASE_DIR / "glossary.json", encoding="utf-8") as f:
    GLOSSARY = json.load(f)

# نام نمایشی منابع توییتری — در پست به جای @آیدی این می‌آید
# می‌توانی در .env با TWITTER_NAMES="handle=نام,handle2=نام" عوض کنی
_TWITTER_NAMES_DEFAULT = (
    "FabrizioRomano=Fabrizio Romano,"
    "David_Ornstein=David Ornstein,"
    "JamesPearceLFC=James Pearce,"
    "DavidLynchLFC=David Lynch,"
    "_pauljoyce=Paul Joyce,"
    "LFC=Liverpool FC,"
    "NicoSchira=Nicolo Schira,"
    "DiMarzio=Gianluca Di Marzio,"
    "TheAthleticFC=The Athletic,"
    "JacobsBen=Ben Jacobs,"
    "LewisSteele_=Lewis Steele,"
    "_ChrisBascombe=Chris Bascombe,"
    "MelissaReddy_=Melissa Reddy,"
    "ptgorst=Paul Gorst,"
    "Plettigoal=Florian Plettenberg,"
    "OptaAnalyst=Opta Analyst,"
    "PhysioScout=Physio Scout,"
    "FMeetsData=Football Meets Data,"
    "DataAnalyticEPL=Data Analytics EPL,"
    "NextGenSector=Next Gen Sector,"
    "AnfieldSector=Anfield Sector,"
    "anfieldsociaI=Anfield Social,"
    "Anfieldmedia_=Anfield Media,"
    "LiverpoolFF=Liverpool FF,"
    "Asim_LFC=Asim,"
    "SajadIqballfc=Sajad Iqbal,"
    "Waleed_Alramahi=Waleed Alramahi,"
    "PartedBeard=Parted Beard,"
    "mnstr_mntlt=Monster Mentality"
)


def _pairs(key, default):
    out = {}
    for chunk in _get(key, default).split(","):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        handle, name = chunk.split("=", 1)
        handle, name = handle.strip().lstrip("@"), name.strip()
        if handle and name:
            out[handle.lower()] = name
    return out


TWITTER_NAMES = _pairs("TWITTER_NAMES", _TWITTER_NAMES_DEFAULT)


def display_name(handle):
    """نام فارسی/انسانی منبع؛ اگر نبود خود آیدی را برمی‌گرداند."""
    h = (handle or "").strip().lstrip("@")
    return TWITTER_NAMES.get(h.lower(), h)
