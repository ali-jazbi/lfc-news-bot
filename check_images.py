"""بررسی اینکه سایت باشگاه واقعاً برای هر خبر چند عکس می‌دهد یا نه.
اجرا: python check_images.py
"""
from sources import lfc_official

items = lfc_official.fetch(limit=6)
print("\u062a\u0639\u062f\u0627\u062f \u062e\u0628\u0631:", len(items))
for it in items:
    imgs = it.get("images") or []
    print("-", (it.get("title") or "")[:60], "\u2192", len(imgs), "\u0639\u06a9\u0633")
