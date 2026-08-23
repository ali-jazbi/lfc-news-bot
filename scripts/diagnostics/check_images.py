"""بررسی اینکه سایت باشگاه واقعاً برای هر خبر چند عکس می‌دهد یا نه.
اجرا: python check_images.py
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import sys as _sys
import pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
from sources import lfc_official

items = lfc_official.fetch(limit=6)
print("\u062a\u0639\u062f\u0627\u062f \u062e\u0628\u0631:", len(items))
for it in items:
    imgs = it.get("images") or []
    print("-", (it.get("title") or "")[:60], "\u2192", len(imgs), "\u0639\u06a9\u0633")
