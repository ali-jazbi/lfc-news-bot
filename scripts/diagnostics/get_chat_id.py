"""گرفتن chat_id گروه تستی.

اجرا:  python get_chat_id.py
سپس در گروه یک پیام بفرست (مثلاً /id). عدد گروه اینجا چاپ می‌شود.
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import sys as _sys
import pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
import time

import config
from telegram_api import Telegram


def main():
    if not config.BOT_TOKEN:
        print("❌ BOT_TOKEN در فایل .env خالی است.")
        return

    tg = Telegram()
    me = tg.get_me()
    if not me:
        print("❌ اتصال به تلگرام برقرار نشد. توکن یا PROXY را چک کن.")
        return

    print(f"✅ متصل شد به @{me.get('username')}")
    print("\U0001F449 حالا در گروه تستی یک پیام بفرست (مثلاً /id) ...\n")

    seen = set()
    offset = None
    deadline = time.time() + 120
    while time.time() < deadline:
        for u in tg.get_updates(offset=offset, timeout=20):
            offset = u["update_id"] + 1
            msg = u.get("message") or u.get("channel_post") or {}
            chat = msg.get("chat", {})
            cid = chat.get("id")
            if cid and cid not in seen:
                seen.add(cid)
                kind = chat.get("type")
                title = chat.get("title") or chat.get("first_name", "")
                print(f"  نوع: {kind:12} | نام: {title}")
                print(f"  ADMIN_CHAT_ID={cid}\n")
        if seen:
            print("این عدد را در فایل .env قرار بده. (Ctrl+C برای خروج)")
    print("زمان تمام شد. دوباره اجرا کن و در گروه پیام بفرست.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
