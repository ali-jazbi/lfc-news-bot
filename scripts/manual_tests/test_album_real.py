"""تست واقعی آلبوم: یک خبر واقعی از سایت می‌گیرد و با عکس‌های واقعی همان خبر
به گروه ادمین sendMediaGroup می‌زند تا مطمئن شویم URL ها در تلگرام درست رندر می‌شوند.

python test_album_real.py            → اولین خبر لیست را تست می‌کند
python test_album_real.py <url>      → همان خبر مشخص را تست می‌کند
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import sys as _sys
import pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
import sys
sys.path.insert(0, ".")

import config
from sources import lfc_official
from telegram_api import Telegram


def main():
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        links = lfc_official._article_links(limit=8)
        url = links[0] if links else None
        if not url:
            print("هیچ لینکی از سایت نیامد")
            return

    art = lfc_official._parse_article(url)
    print("خبر:", art["title"])
    print("images (%d):" % len(art["images"]))
    for u in art["images"]:
        print("   *", u)

    if len(art["images"]) < 2:
        print("این خبر کمتر از ۲ عکس دارد — آلبوم فرستاده نمی‌شود")
        return

    tg = Telegram()
    res = tg.send_media_group(
        config.ADMIN_CHAT_ID,
        art["images"],
        caption=f"تست آلبوم واقعی: {art['title'][:60]}",
    )
    if res:
        print("OK — آلبوم رفت، تعداد پیام:", len(res))
    else:
        print("FAIL:", tg.last_error)


if __name__ == "__main__":
    main()
