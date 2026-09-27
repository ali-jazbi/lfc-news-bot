"""دو سیکل پشت‌سرهم واقعی: ثابت می‌کند state/since/dedup واقعاً کار می‌کند.

سیکل ۱: از هر حساب فقط «جدیدترین توییت» را برمی‌دارد (صفحه‌ی اول) و state
         (`fxembed_since`) را پر می‌کند — مثل اولین اجرای بات.
سیکل ۲: همان `since` را می‌فرستد و ثابت می‌کند که دوباره همان توییت‌ها برمی‌گردند
         (حاشیه‌ی ۹۰۰ ثانیه‌ای عمدی است) و هیچ توییتی بین دو سیکل گم نمی‌شود.

اجرا:  python scripts/manual_tests/test_fxembed_cycles.py [تعداد_حساب]
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

n_arg = sys.argv[1] if len(sys.argv) > 1 else ""
if "," in n_arg:                       # فهرست صریح handleها
    accounts = [a.strip().lstrip("@") for a in n_arg.split(",") if a.strip()]
else:
    tier1, rest = twitter._accounts()
    accounts = (tier1 + rest)[:int(n_arg or 6)]
overlap = config.FXEMBED_SINCE_OVERLAP_SECONDS
per_account = config.FXEMBED_TWEETS_PER_ACCOUNT


def scrape_since(u, since):
    return {e["link"].split("/")[-1]: e for e in
            fxembed.scrape_user(u, per_account, since)}


def new_ts(entries):
    from email.utils import parsedate_to_datetime
    best = 0
    for e in entries.values():
        try:
            best = max(best, int(parsedate_to_datetime(e["published"]).timestamp()))
        except Exception:
            pass
    return best


def run_cycle(label, since_map):
    """since_map دقیقاً همان چیزی است که بات می‌فرستد: آخرین زمان منهای حاشیه."""
    t0 = time.time()
    out = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(scrape_since, u, since_map.get(u.lower())): u
                for u in accounts}
        for f in as_completed(futs):
            out[futs[f]] = f.result()
    new_map = {}
    for u, entries in out.items():
        if entries:
            new_map[u.lower()] = new_ts(entries)
    total = sum(len(e) for e in out.values())
    print("[%s] %d حساب · %d توییت · %.1fs" % (label, len(out), total,
                                                 time.time() - t0), flush=True)
    return out, new_map


print("=== دو سیکل واقعی روی %s (overlap=%ss) ===" % (", ".join(accounts), overlap))

c1, map1 = run_cycle("سیکل ۱", {})                     # مثل اولین اجرای بات
susp = {}
for u, accounts_ in c1.items():
    if accounts_:
        newest = max(accounts_.values(), key=lambda e: int(e["link"].split("/")[-1]))
        print("  @%-16s جدیدترین: %s · %s" % (
            u, newest["link"].split("/")[-1],
            newest["summary"][:45].replace("\n", " ")))
    else:
        reason = fxembed.suspension_reason(u)
        print("  @%-16s بدون نتیجه → %s" % (u, reason or "خطای گذرا (سیکل بعد retry)"))
        if reason:
            susp[u] = reason

# دقیقاً همان چیزی که sources/twitter.py در سیکل بعد می‌فرستد
since_for_bot = {u: (v - overlap) for u, v in map1.items()}
c2, map2 = run_cycle("سیکل ۲", since_for_bot)         # با since = آخرین زمان − حاشیه

print("\n--- بررسی ---")
checked = [u for u in c1 if c1[u]]
lost, repeated, fresh = [], 0, 0
for u in checked:
    missing = set(c1[u]) - set(c2.get(u, {}))
    if missing:
        lost.append((u, sorted(missing)[:3], len(missing)))
    repeated += len(set(c1[u]) & set(c2.get(u, {})))
    fresh += len(set(c2.get(u, {})) - set(c1[u]))
print("توییت‌های سیکل ۱ که در سیکل ۲ نبودند (باید ۰ باشد): %d" % len(lost))
for u, ids, n in lost:
    print("   ✗ @%s → %d توییت گم شد، نمونه: %s" % (u, n, ids))
print("توییت‌های تکراری (حاشیه‌ی ۱۵ دقیقه‌ای عمدی است): %d" % repeated)
print("توییت‌های تازه‌ی سیکل ۲: %d" % fresh)
print("حساب‌های ساسپند/حذف‌شده شناسایی‌شده: %s" % (susp or "هیچ"))
print("اجرای بعدی بات این‌ها را skip می‌کند: %s" % (", ".join(susp) or "—"))
