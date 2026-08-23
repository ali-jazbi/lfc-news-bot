"""اسکلت تست دستی @twittervid_bot — فعلاً پیاده‌سازی نشده.

چرا اسکلت؟ چون Bot API تلگرام اجازه نمی‌دهد بات به بات پیام بدهد. برای
صحبت با @twittervid_bot به یک اکانت کاربر واقعی (Telethon/MTProto) لازم
است: API_ID + API_HASH از my.telegram.org و یک سشن لاگین‌شده. قبل از
هر کاری باید دستی جوین اسپانسرِ آن بات شوی و دید اصلاً به ما جواب
می‌دهد یا نه (خیلی از این دانلودرها ریت‌لیمیت سخت دارند).

وقتی این سه متغیر را در .env گذاشتی، این اسکریپت کامل می‌شود:
    TWITTERVID_API_ID=12345
    TWITTERVID_API_HASH=abcdef...
    TWITTERVID_SESSION=<نام فایل سشن یا StringSession>

اجرا:
    python scripts/manual_tests/test_twittervid_bot.py <لینک_توییت>
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import os
import sys
import pathlib as _pathlib
_sys = sys
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
# کنسول ویندوزی ممکن است UTF-8 نباشد — خروجی فارسی خراب نشود
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

API_ID = os.environ.get("TWITTERVID_API_ID", "").strip()
API_HASH = os.environ.get("TWITTERVID_API_HASH", "").strip()
SESSION = os.environ.get("TWITTERVID_SESSION", "").strip()
BOT_USERNAME = "twittervid_bot"


def _require_env():
    missing = [k for k, v in (
        ("TWITTERVID_API_ID", API_ID),
        ("TWITTERVID_API_HASH", API_HASH),
        ("TWITTERVID_SESSION", SESSION),
    ) if not v]
    if missing:
        print("❌ این متغیرهای .env خالی‌اند: %s" % ", ".join(missing))
        print("   راهنما در هدر همین فایل. تا آن موقع این قابلیت فعال نمی‌شود.")
        return False
    return True


def start_client():
    """سشن Telethon را بالا می‌آورد — بعد از تأمین env پیاده‌سازی می‌شود."""
    raise NotImplementedError(
        "pip install telethon — و بعد بدنهٔ این تابع نوشته می‌شود")


def request_video(client, tweet_url):
    """لینک توییت را به @twittervid_bot می‌فرستد."""
    raise NotImplementedError


def poll_reply(client, timeout=120):
    """پاسخ بات (فایل/لینک مدیا) را برمی‌گرداند."""
    raise NotImplementedError


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("استفاده: %s <لینک توییت>" % sys.argv[0])
        return 1 if _require_env() else 0
    tweet_url = sys.argv[1]
    if not _require_env():
        return 0   # بدون env فقط اطلاع‌رسانی — خطا نیست
    print("⚠ پیاده‌سازی هنوز انجام نشده؛ لینک دریافتی:", tweet_url)
    return 1


if __name__ == "__main__":
    sys.exit(main())
