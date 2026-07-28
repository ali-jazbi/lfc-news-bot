"""تست حساب‌های توییتر — موازی و روی چند آینه.

    python check_accounts.py

اول همه آینه‌ها را رتبه‌بندی می‌کند، بعد همه حساب‌ها را همزمان می‌خواند؛
حسابی که روی آینه اول جواب ندهد، روی آینه‌های بعدی هم امتحان می‌شود.
پس برخلاف قبل، نتیجه هر بار عوض نمی‌شود و خیلی سریع‌تر است.
"""
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.CRITICAL)

import config
from sources import twitter
from sources.base import clean_text

OK, NO = "\u2705", "\u274c"
LINE = "\u2500" * 66
MAX_BASES = 3          # حداکثر چند آینه برای تلاش دوباره
WORKERS = 8


def test_account(user, bases):
    """حساب را روی آینه‌ها به ترتیب امتحان می‌کند تا جایی که جواب بگیرد."""
    t0 = time.time()
    for base in bases:
        entries = twitter.read_feed(base, user)
        if entries:
            return {
                "user": user,
                "ok": True,
                "count": len(entries),
                "secs": round(time.time() - t0, 1),
                "base": base,
                "head": clean_text(entries[0].get("title") or "")[:50],
            }
    return {
        "user": user,
        "ok": False,
        "count": 0,
        "secs": round(time.time() - t0, 1),
        "base": "",
        "head": "",
    }


def main():
    print("\u0633\u0646\u062c\u06cc\u062f\u0646 \u0622\u06cc\u0646\u0647\u200c\u0647\u0627 \u2026")
    ranked = twitter.rank_bases()
    for base, count, secs in ranked:
        mark = OK if count >= 3 else NO
        print("  " + mark + " " + base.ljust(40) + str(count).rjust(3)
              + " توییت · " + str(secs) + "s")

    healthy = [r[0] for r in ranked if r[1] >= 3][:MAX_BASES]
    if not healthy:
        print(NO + " هیچ آینه سالمی پیدا نشد.")
        print("   اگر بالا همه صفر یا ۱ هستند، یا فیلتری، یا آینه‌ها موقتاً خوابند.")
        print("   در .env مقدار PROXY را پر کن و دوباره بزن.")
        sys.exit(1)

    print("\nآینه‌های در دسترس: " + "، ".join(healthy))
    print(LINE)

    tier1 = {a.lstrip("@").lower() for a in config.TWITTER_TIER1}
    accounts = [a.lstrip("@") for a in config.TWITTER_ACCOUNTS]

    t0 = time.time()
    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(test_account, u, healthy): u for u in accounts}
        for fut in as_completed(futures):
            r = fut.result()
            results[r["user"]] = r

    good, bad = [], []
    for user in accounts:                      # ترتیب ثابت در خروجی
        r = results.get(user) or {"ok": False, "count": 0, "secs": 0, "head": ""}
        star = "\u2b50" if user.lower() in tier1 else "  "
        if r["ok"]:
            good.append(user)
            print(OK + star + " @" + user.ljust(18) + str(r["count"]).rjust(3)
                  + " توییت · " + str(r["secs"]) + "s · " + r["head"])
        else:
            bad.append(user)
            print(NO + star + " @" + user.ljust(18) + "جواب نداد (روی "
                  + str(len(healthy)) + " آینه)")

    print(LINE)
    print(OK + " سالم: " + str(len(good)) + "   " + NO + " مشکوک: " + str(len(bad))
          + "   · کل زمان: " + str(round(time.time() - t0, 1)) + "s")

    if bad:
        print("\nحساب‌هایی که جواب ندادند (غلط نوشته شده، پرایوت، یا فقط کند):")
        print("  " + ", ".join("@" + b for b in bad))
        print("  یک بار دیگر اسکریپت را بزن؛ اگر باز همین‌ها بودند، املایشان را بفرست.")

    print("\nاگر خواستی فقط حساب‌های سالم بمانند، این خط را در .env بگذار")
    print("(دقت کن از خود ترمینال کپی کنی تا آندرلاین‌ها خراب نشوند):\n")
    print("TWITTER_ACCOUNTS=" + ",".join(good))


if __name__ == "__main__":
    main()
