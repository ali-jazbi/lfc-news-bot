"""تست دستی منبع FxEmbed/FxTwitter روی همه‌ی حساب‌های واقعی پروژه.

این تست از *مسیر خودِ بات* می‌رود (sources.fxembed.scrape_user) — نه HTTP خام —
تا همان چیزی آزمایش شود که در پروداکشن اجرا می‌شود. نیاز به اینترنت دارد.

اجرا:
    python scripts/manual_tests/test_fxembed.py [تعداد_حساب]
    TWITTER_MODE=fxembed python main.py --once --dry-run   # تست کامل پایپ‌لاین
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import os
import sys
import pathlib as _pathlib
import time

_root = str(_pathlib.Path(__file__).resolve().parents[2])
sys.path.insert(0, _root)
os.chdir(_root)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from sources import fxembed, twitter

n = int(sys.argv[1]) if len(sys.argv) > 1 else 99
tier1, rest = twitter._accounts()
accounts = (tier1 + rest)[:n]

print("=== تست زنده‌ی FxEmbed/FxTwitter — %d حساب (mode=%s) ===" % (
    len(accounts), config.TWITTER_MODE))
print("منبع: %s · timeout=%ss · tries=%s\n" % (
    config.FXEMBED_BASE, config.FXEMBED_TIMEOUT, config.FXEMBED_FETCH_TRIES))

rows = {}


def check(user):
    t0 = time.time()
    entries = fxembed.scrape_user(user, config.FXEMBED_TWEETS_PER_ACCOUNT)
    media = sum(1 for e in entries if e.get("image"))
    vids = sum(1 for e in entries
               if any(m["type"] == "video" for m in (e.get("_xscrape_media") or [])))
    quotes = sum(1 for e in entries if e.get("_xscrape_quoted"))
    newest = entries[0]["published"] if entries else None
    return {
        "user": user,
        "count": len(entries),
        "media": media,
        "video": vids,
        "quote": quotes,
        "head": (entries[0]["summary"][:60].replace("\n", " ") if entries else ""),
        "newest": newest,
        "secs": round(time.time() - t0, 1),
    }


with ThreadPoolExecutor(max_workers=6) as pool:
    futures = {pool.submit(check, u): u for u in accounts}
    for fut in as_completed(futures):
        r = fut.result()
        rows[r["user"]] = r
        mark = "✓" if r["count"] else "✗"
        print("%s @%-20s %3d توییت · عکس %2d · ویدیو %2d · نقل‌قول %2d · %5.1fs · %s"
              % (mark, r["user"], r["count"], r["media"], r["video"], r["quote"],
                 r["secs"], r["head"]), flush=True)

ok = [r for r in rows.values() if r["count"]]
bad = [r for r in rows.values() if not r["count"]]
total_tweets = sum(r["count"] for r in ok)
print("\n--- خلاصه ---")
print("%d حساب · موفق %d · ناموفق %d · نرخ موفقیت %.1f%%"
      % (len(rows), len(ok), len(bad), 100.0 * len(ok) / max(1, len(rows))))
print("کل توییت دریافتی: %d · حساب با مدیا: %d · با ویدیو: %d · با نقل‌قول: %d"
      % (total_tweets, sum(1 for r in ok if r["media"]),
         sum(1 for r in ok if r["video"]), sum(1 for r in ok if r["quote"])))
if bad:
    print("ناموفق‌ها: " + "، ".join("@" + r["user"] for r in bad))
    print("(حساب ساسپند/حذف‌شده هیچ منبعی ندارد — بقیه باید بررسی شوند.)")
