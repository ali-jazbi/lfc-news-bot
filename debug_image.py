"""بررسی دقیق متاتگ‌های عکس یک خبر واقعی — مستقل از آلبوم، فقط تشخیص.
اجرا: python debug_image.py "https://www.liverpoolfc.com/news/..."
"""
import sys
from sources.base import http_get, soup_of, meta

url = sys.argv[1] if len(sys.argv) > 1 else "https://www.liverpoolfc.com/news/andoni-iraola-offers-update-joe-gomez-injury"
html = http_get(url)
print("URL:", url)
print("HTML length:", len(html) if html else None)
if not html:
    print("\u062f\u0627\u0646\u0644\u0648\u062f \u0646\u0627\u0645\u0648\u0641\u0642 \u0628\u0648\u062f (http_get None)")
    sys.exit(0)
s = soup_of(html)
print("og:title ->", meta(s, "og:title"))
print("og:image ->", meta(s, "og:image"))
print("twitter:image ->", meta(s, "twitter:image"))
print("--- \u0647\u0645\u0647 \u0645\u062a\u0627\u062a\u06af\u200c\u0647\u0627\u06cc\u06cc \u06a9\u0647 \u06a9\u0644\u0645\u0647 image \u062f\u0627\u0631\u0646\u062f ---")
for tag in s.find_all("meta"):
    prop = tag.get("property") or tag.get("name") or ""
    if "image" in prop.lower():
        print(prop, "=", tag.get("content"))
print("--- \u062a\u0639\u062f\u0627\u062f \u062a\u06af \u0647\u0627\u06cc img \u062f\u0631 \u06a9\u0644 \u0635\u0641\u062d\u0647 ---")
print(len(s.find_all("img")))
