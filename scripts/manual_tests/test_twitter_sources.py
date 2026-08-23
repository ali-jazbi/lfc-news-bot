"""تست دستی منبع توییتر — این را جایی بزن که اینترنت واقعی دارد
(لوکال یا روی سرور)، نه در محیط توسعه‌ی من که اصلاً به بیرون وصل ندارد.

خروجی نشان می‌دهد برای هر حساب کدام لایه (سندیکیشن یا کدام آینه‌ی نیتر) جواب داد.
خروجی این اسکریپت را برایم کپی/پیست کن تا بر اساس نتیجه واقعی ادامه بدیم.
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import sys as _sys
import pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
import config
from sources import twitter

tier1, rest = twitter._accounts()
accounts = (tier1 + rest)[:15]

print("=== لایه ۱: سندیکیشن مستقیم مستقیم توییتر (بدون آینه) ===")
synd_ok = 0
for u in accounts:
    entries = twitter.syndication_fetch(u)
    status = "✓ %d توییت" % len(entries) if entries else "✗ جواب نداد"
    print("@%-20s -> %s" % (u, status))
    if entries:
        synd_ok += 1
        print("   نمونه:", entries[0]["title"][:90].replace("\n", " "))
print("\nجمع: %d از %d حساب با سندیکیشن جواب دادند" % (synd_ok, len(accounts)))

print("\n=== لایه ۲: رتبه‌بندی آینه‌های نیتر (برای حساب‌هایی که لایه ۱ جواب نداد) ===")
for base, count, secs in twitter.rank_bases():
    print("%-45s %2d توییت   %ss" % (base, count, secs))

print("\n=== وضعیت backoff آینه‌ها ===")
health = twitter._mirror_health()
if not health:
    print("(هنوز هیچ آینه‌ای شکست نخورده)")
for base, info in health.items():
    print("%-45s شکست‌های پیاپی: %d" % (base, info.get("fails", 0)))

print("\n=== fetch() نهایی (همان چیزی که ربات استفاده می‌کند) ===")
items = twitter.fetch(limit=10)
for it in items:
    print("-", it["source_tag"], "|", it["title"][:90].replace("\n", " "))
print("\nجمع: %d خبر" % len(items))
