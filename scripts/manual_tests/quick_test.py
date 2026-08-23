"""تست سریع یک جمله دلخواه با یک مدل مشخص (بدون دست زدن به .env اصلی).

استفاده:
    python quick_test.py

مدل مورد تست را با تغییر SLOT عوض کن (مثلاً "llm6" برای qwen).
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import sys as _sys
import pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
import config

SLOT = "llm6"  # اسم اسلاتی که می‌خوای تست کنی: llm1 ... llm10
config.TRANSLATE_ORDER = [SLOT]

import translate

item = {
    "source_tag": "تست دستی",
    "title": "",
    "body": "Liverpool have reached an agreement to sign the winger for £40m.",
}

result = translate.translate(item)
print(result)
