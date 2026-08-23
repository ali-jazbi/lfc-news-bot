"""تست نگهبان کانال.

    python check_channel.py                 → چند پست اخیر کانال خوانده می‌شود
    python check_channel.py "متن تست"      → شباهت این متن با پست‌های کانال
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import sys as _sys
import pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

import channel_guard
import config

OK, NO = "\u2705", "\u274c"
LINE = "\u2500" * 60


def main():
    print("کانال: " + str(config.CHANNEL_USERNAME))
    print("آستانه شباهت: " + str(channel_guard.cfg("CHANNEL_GUARD_THRESHOLD")) + "%")
    if not hasattr(config, "CHANNEL_GUARD_THRESHOLD"):
        print("\u26a0\ufe0f  config.py قدیمی است — فعلاً مقدار پیش‌فرض استفاده می‌شود")
    print(LINE)

    posts = channel_guard.refresh(force=True)
    if not posts:
        print(NO + " هیچ پستی خوانده نشد.")
        print("   دلایل ممکن: کانال خصوصی است، نام کاربری غلط است، یا t.me فیلتر است.")
        print("   راه دور زدن: در .env مقدار PROXY را پر کن یا CHANNEL_GUARD=false بگذار.")
        sys.exit(1)

    print(OK + " " + str(len(posts)) + " پست اخیر خوانده شد\n")
    for p in posts[-5:]:
        print("  \u2022 " + p[:90].replace("\n", " "))

    if len(sys.argv) > 1:
        probe = " ".join(sys.argv[1:])
        print("\n" + LINE)
        print("متن تست: " + probe[:80])
        hit = channel_guard.check({"title": probe, "body": ""})
        if hit:
            score, sample = hit
            print(NO + " تکراری تشخیص داده شد — شباهت " + str(score) + "%")
            print("   پست مشابه: " + sample)
        else:
            print(OK + " تکراری نیست — این خبر به گروه می‌رفت")


if __name__ == "__main__":
    main()
