"""تست دستی اسکرپ x.com — این را جایی بزن که اینترنت واقعی دارد
(لوکال یا روی سرور)، نه در محیط بدون شبکه.

خروجی نشان می‌دهد برای هر حساب اسکرپ مستقیم x.com چند توییت داد و مدیا
داشت یا نه. خروجی این اسکریپت را برایم کپی/پیست کن تا بر اساس نتیجه
واقعی ادامه بدیم.

اجرا:
    TWITTER_MODE=xscrape python scripts/manual_tests/test_xscrape.py [تعداد_حساب]
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import sys
import pathlib as _pathlib
sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
# کنسول ویندوزی ممکن است UTF-8 نباشد — خروجی فارسی خراب نشود
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config
from sources import twitter, xscrape

n = int(sys.argv[1]) if len(sys.argv) > 1 else 10

tier1, rest = twitter._accounts()
accounts = (tier1 + rest)[:n]

print("=== اسکرپ مستقیم x.com (TWITTER_MODE=%s) ===" % config.TWITTER_MODE)
print("حساب‌ها: %d\n" % len(accounts))

ok = 0
for u in accounts:
    entries = xscrape.scrape_user(u)
    status = "✓ %d توییت" % len(entries) if entries else "✗ جواب نداد"
    print("@%-20s -> %s" % (u, status))
    if not entries:
        continue
    ok += 1
    e = entries[0]
    media = e.get("_xscrape_media") or []
    kinds = ["%s×%d" % (m["type"], sum(1 for x in media if x["type"] == m["type"]))
             for m in media] or ["بدون مدیا"]
    print("   متن:", (e["summary"] or "")[:90].replace("\n", " "))
    print("   مدیا:", ", ".join(kinds))

print("\nنتیجه: %d/%d حساب جواب داد" % (ok, len(accounts)))
if ok == 0:
    print("⚠ هیچ حسابی جواب نداد — احتمالاً x.com این IP را بلاک کرده یا فرمت عوض شده.")
    print("  با XSCRAPE_FALLBACK_CLASSIC=true بات خودکار به نیتر برمی‌گردد.")
