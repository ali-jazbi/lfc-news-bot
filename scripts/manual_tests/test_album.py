"""تست مستقل آلبوم (group photo) — کاری به اسکریپر/ترجمه ندارد.

اجرا: python test_album.py
فقط بررسی می‌کند که send_media_group در telegram_api.py درست کار می‌کند؛
سه عکس نمونه (بی‌ربط به لیورپول) می‌فرستد به ADMIN_CHAT_ID.
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import sys as _sys
import pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
import config
from telegram_api import Telegram

tg = Telegram()
images = [
    "https://picsum.photos/id/237/900/600",
    "https://picsum.photos/id/238/900/600",
    "https://picsum.photos/id/239/900/600",
]

print("\u0627\u0631\u0633\u0627\u0644 \u0622\u0644\u0628\u0648\u0645 \u0628\u0647 chat_id:", config.ADMIN_CHAT_ID)
res = tg.send_media_group(config.ADMIN_CHAT_ID, images, caption="\u062a\u0633\u062a \u0622\u0644\u0628\u0648\u0645 \u2014 \u0633\u0647 \u0639\u06a9\u0633")
if res:
    print("OK \u2014 \u0622\u0644\u0628\u0648\u0645 \u0631\u0641\u062a. \u062a\u0639\u062f\u0627\u062f \u067e\u06cc\u0627\u0645: ", len(res))
else:
    print("\u0646\u0634\u062f. last_error:", tg.last_error)
