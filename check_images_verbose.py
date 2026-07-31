"""ابزار تشخیص: برای هر خبر نشان می‌دهد کدام عکس پذیرفته شده و کدام رد شده (و چرا).
با این خروجی دقیقاً معلوم می‌شود عکس سفید/تکراری از کدام مسیر آمده است.
"""
import sys
sys.path.insert(0, ".")

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from sources import lfc_official as lo


def main():
    urls = [u.strip() for u in sys.argv[1:]]
    if not urls:
        html = lo.http_get("https://www.liverpoolfc.com/news")
        urls = lo._article_links(limit=8) if html else []

    for url in urls:
        print("=" * 100)
        print("URL:", url)
        html = lo.http_get(url)
        if not html:
            print("!! صفحه گرفته نشد")
            continue
        soup = BeautifulSoup(html, "html.parser")
        og = lo.meta(soup, "og:image")
        print("og:image ->", og)

        container = (
            soup.find("article")
            or soup.find(attrs={"class": lo.re.compile(r"article|content|body", lo.re.I)})
            or soup
        )
        imgs = container.find_all("img")
        print("تعداد img در container:", len(imgs))

        for i, img in enumerate(imgs[:16]):
            cand = []
            for attr in ("data-src", "data-srcset", "srcset", "src"):
                v = img.get(attr)
                if v:
                    if "," in v:
                        v = v.split(",")[-1].strip().split(" ")[0]
                    cand.append(v)
                    break
            v = cand[0] if cand else None
            if not v:
                print(f"[{i}] بدون src — رد")
                continue
            u = urljoin("https://www.liverpoolfc.com", v.strip())
            path = u.split("?")[0].split("#")[0]
            key = lo._img_key(u)
            reasons = []
            if v.strip().startswith("data:"):
                reasons.append("data:/base64")
            if any(x in u.lower() for x in lo._IMG_SKIP):
                reasons.append("کلمه پرچم در آدرس")
            if not path.lower().endswith(lo._IMG_EXT):
                reasons.append("پسوند نامعتبر: " + (path.rsplit(".", 1)[-1] if "." in path else "بدون پسوند"))
            if lo._IMG_CONTENT_PATH not in u.lower():
                reasons.append("خارج از مسیر فایل‌های محتوایی")
            print(f"[{i}] {'رد' if reasons else 'قبول'} | {u[:110]}")
            print(f"     فایل: {key[:60]} | دلیل: {'، '.join(reasons) or '—'}")

        final = lo._article_images(soup, og)
        print("-" * 60)
        print("نتیجه نهایی images (%d):" % len(final))
        for u in final:
            print("   *", u[:120])
    print("=" * 100)


if __name__ == "__main__":
    main()
