"""تست زنده فیدهای رومانو — کدام پل هنوز کار می‌کند؟

    python check_feeds.py

هر آدرس را می‌گیرد، تعداد آیتم و تازه‌ترین تیتر را نشان می‌دهد.
خط سبزی که دیدی را در .env در ROMANO_FEEDS اول بگذار.
"""
import logging
import sys
import time

logging.basicConfig(level=logging.CRITICAL)

import config
from sources.base import parse_rss
from sources import romano

OK, NO = "\u2705", "\u274c"

EXTRA = [
    "https://xcancel.com/FabrizioRomano/rss",
    "https://nitter.net/FabrizioRomano/rss",
    "https://lightbrd.com/FabrizioRomano/rss",
    "https://nitter.tiekoetter.com/FabrizioRomano/rss",
    "https://nitter.privacyredirect.com/FabrizioRomano/rss",
    "https://nitter.space/FabrizioRomano/rss",
    "https://rsshub.rssforever.com/twitter/user/FabrizioRomano",
    "https://rsshub.pseudoyu.com/twitter/user/FabrizioRomano",
    romano.GOOGLE_FALLBACK,
]


def main():
    urls = []
    for u in list(config.ROMANO_FEEDS) + EXTRA:
        if u and u not in urls:
            urls.append(u)

    print("تست " + str(len(urls)) + " فید — ممکن است یکی دو دقیقه طول بکشد\n")
    working = []

    for u in urls:
        t0 = time.time()
        try:
            items = parse_rss(u)
        except Exception as e:
            items = []
            print(NO + " " + u)
            print("   \u2514\u2500 " + str(e)[:120])
            continue
        dt = round(time.time() - t0, 1)
        if items:
            working.append(u)
            head = (items[0].get("title") or "")[:70]
            print(OK + " " + u)
            print("   \u2514\u2500 " + str(len(items)) + " آیتم · " + str(dt) + "s · " + head)
        else:
            print(NO + " " + u + "   (خالی یا خطا)")

    print("\n" + "\u2500" * 60)
    if not working:
        print(NO + " هیچ فیدی جواب نداد.")
        print("   گزینه امن: ENABLE_ROMANO=false و فعلاً فقط سایت باشگاه.")
        sys.exit(1)

    print(OK + " " + str(len(working)) + " فید سالم است. این خط را در .env بگذار:\n")
    print("ROMANO_FEEDS=" + ",".join(working))


if __name__ == "__main__":
    main()
