"""تست مستقیم ارسال تلگرام — می‌گوید دقیقاً کدام مرحله می‌شکند و چرا.

    python test_send.py
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import sys as _sys
import pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

import config
import formatter
import sample_item
from telegram_api import Telegram

OK, NO = "\u2705", "\u274c"


def result(label, res, tg):
    if res:
        print(OK + " " + label + "  (message_id=" + str(res.get("message_id")) + ")")
    else:
        print(NO + " " + label)
        print("   \u2514\u2500 دلیل: " + (tg.last_error or "پاسخی نیامد (شبکه/پراکسی)"))
    return res


def main():
    if not config.BOT_TOKEN or not config.ADMIN_CHAT_ID:
        print(NO + " BOT_TOKEN یا ADMIN_CHAT_ID در .env خالی است")
        sys.exit(1)

    tg = Telegram()
    chat = config.ADMIN_CHAT_ID

    me = tg.get_me()
    if not me:
        print(NO + " اتصال به تلگرام برقرار نشد: " + str(tg.last_error))
        sys.exit(1)
    print(OK + " ربات: @" + str(me.get("username")) + "   |   گروه: " + str(chat))
    print("\u2500" * 60)

    item = sample_item.get(0)
    image = item.get("image")

    m1 = result("۱) پیام متنی ساده",
                tg.send_message(chat, "\U0001f9ea تست ۱ — پیام متنی"), tg)

    if m1:
        result("۲) ریپلای روی پیام ۱",
               tg.send_message(chat, "\U0001f9ea تست ۲ — این باید ریپلای باشد",
                               silent=True, reply_to=m1.get("message_id")), tg)
    else:
        print(NO + " ۲) ریپلای — رد شد (پیام ۱ نرفت)")

    original = formatter.build_original_message(item)
    m3 = result("۳) بلاک‌کووت تاشو (قالب متن اصلی)",
                tg.send_message(chat, original, silent=True,
                                reply_to=m1.get("message_id") if m1 else None), tg)
    if not m3:
        result("۳ب) همان متن بدون بلاک‌کووت",
               tg.send_message(chat,
                               formatter.build_original_message(item, expandable=False),
                               silent=True), tg)

    print("\nعکس تست: " + str(image))
    if str(image).startswith("http"):
        r4 = tg.call("sendPhoto", chat_id=chat, photo=image,
                     caption="\U0001f9ea تست ۴ — عکس از طریق URL", parse_mode="HTML")
        result("۴) عکس با URL (خود تلگرام دانلود کند)", r4, tg)
    else:
        r4 = None
        print("ℹ️  ۴) رد شد — عکس نمونه حالا فایل محلی است، در تست ۶ چک می‌شود")

    if not r4 and str(image).startswith("http"):
        blob = tg.fetch_image(image)
        if not blob:
            print(NO + " ۵) خودت هم نتوانستی این URL را بگیری — دلیل: " + str(tg.last_error))
            print("      (HTTP ۴۰۰/۴۰۳/۴۰۴ یعنی آدرس خراب است، نه شبکه)")
        else:
            print("   دانلود موفق: " + str(len(blob)) + " بایت")
            result("۵) آپلود مستقیم همان عکس",
                   tg.upload_photo(chat, blob, "\U0001f9ea تست ۵ — آپلود مستقیم"), tg)

    # ۶) عکس محلی — بدون هیچ وابستگی به اینترنت بیرونی
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "..", "assets", "sample.png")
    if os.path.isfile(local):
        result("۶) عکس محلی assets/sample.png",
               tg.send_photo(chat, local, "\U0001f9ea تست ۶ — عکس از روی دیسک"), tg)
    else:
        print(NO + " ۶) فایل assets/sample.png پیدا نشد")

    print("\u2500" * 60)
    print("هر خط قرمزی را با دلیلش بفرست.")


if __name__ == "__main__":
    main()
