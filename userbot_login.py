"""اسکریپت ورود اولیه یوزربات (فقط یک بار اجرا می‌شود تا سشن ساخته شود)."""
import asyncio
import os
from telethon import TelegramClient
from telethon.errors import AuthKeyDuplicatedError
import config


async def main():
    api_id = getattr(config, "USERBOT_API_ID", None)
    api_hash = getattr(config, "USERBOT_API_HASH", None)
    session_name = getattr(config, "USERBOT_SESSION", "lfc_userbot")

    if not api_id or not api_hash:
        print("❌ لطفاً ابتدا USERBOT_API_ID و USERBOT_API_HASH را در فایل .env وارد کنید.")
        print("   این دو مقدار را به صورت رایگان از سایت my.telegram.org دریافت می‌کنید.")
        return

    proxy = None
    if config.PROXY:
        try:
            from urllib.parse import urlparse
            p = urlparse(config.PROXY)
            import socks
            ptype = socks.SOCKS5 if "socks5" in p.scheme else socks.HTTP
            proxy = (ptype, p.hostname, p.port)
        except Exception:
            pass

    if os.path.exists(session_name + ".session"):
        print(f"⚠️ فایل سشن «{session_name}.session» از قبل وجود دارد.")
        print("   اگر ارور AuthKeyDuplicatedError گرفتی، اول این فایل را حذف کن و دوباره اجرا کن.")
        print("   توجه: هر سشن فقط روی «یک» ماشین/پروسه استفاده شود — استفاده هم‌زمان از دو IP سشن را برای همیشه می‌سوزاند.")

    print(f"🔹 در حال اتصال به تلگرام با سشن: {session_name}...")
    client = TelegramClient(session_name, int(api_id), str(api_hash), proxy=proxy)
    try:
        await client.start()
    except AuthKeyDuplicatedError:
        print("❌ این سشن باطل شده (AuthKeyDuplicatedError) — با دو IP مختلف استفاده شده است.")
        print(f"   فایل «{session_name}.session» را حذف کن و این اسکریپت را دوباره اجرا کن.")
        print("   مطمئن شو سشن جدید فقط روی همین یک ماشین استفاده می‌شود.")
        return
    me = await client.get_me()
    print(f"✅ لاگین با موفقیت انجام شد! کاربر متصل: {me.first_name} (@{me.username})")
    print("فایل سشن ذخیره شد. از این پس ربات می‌تواند ویدیوها را خودکار و ابری از @twittervid_bot دریافت کند.")


if __name__ == "__main__":
    asyncio.run(main())
