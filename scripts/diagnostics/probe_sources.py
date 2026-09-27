"""کاوش زنده‌ی دو منبع توییتر: x.com خام و FxEmbed/FxTwitter API.

این اسکریپت عمداً «خارج از مسیر بات» کار می‌کند (requests خام) تا وضعیت واقعی
هر منبع دیده شود، نه آنچه لایه‌های retry/parse بات نشان می‌دهند. نتیجه‌ها
تدریجی در یک فایل JSON ذخیره می‌شوند تا بتوان اجرا را به تکه‌های کوچک شکست
(هر تکه فقط بخشی از حساب‌ها).

اجرا:
    python scripts/diagnostics/probe_sources.py x --start 0 --count 5
    python scripts/diagnostics/probe_sources.py fx --start 0 --count 29
    python scripts/diagnostics/probe_sources.py fx-summary
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import json
import os
import pathlib as _pathlib
import re
import sys
import time

_sys_path_root = str(_pathlib.Path(__file__).resolve().parents[2])
sys.path.insert(0, _sys_path_root)
os.chdir(_sys_path_root)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import config
from sources import twitter

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

X_PROBE_PATH = os.path.join("logs", "probe_x.json")
FX_PROBE_PATH = os.path.join("logs", "probe_fxembed.json")
FX_BASE = "https://api.fxtwitter.com"

# نشانه‌های ساختار صفحه‌ی x.com — برای تشخیص اینکه داده‌ی SSR/relay هنوز هست یا نه
X_MARKERS = (
    "relayRecords",
    "TBirdData",
    "graphql",
    "UserTweets",
    "UserByScreenName",
    "__INITIAL_STATE__",
    "initialState",
    "Just a moment",
    "challenge",
    "Enable JavaScript",
    "log in",
)


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _accounts():
    tier1, rest = twitter._accounts()
    return tier1 + rest
# --------------------------------------------------------------- x.com خام
def probe_x(user, timeout=8):
    """(HTTP status, طول بدنه, نشانه‌ها) برای صفحه‌ی پروفایل x.com."""
    out = {"account": user, "url": "https://x.com/%s" % user}
    t0 = time.time()
    try:
        r = requests.get(out["url"], headers={"User-Agent": UA}, timeout=timeout)
    except Exception as e:
        out.update({"status": None, "error": "%s: %s" % (type(e).__name__, e),
                    "secs": round(time.time() - t0, 2)})
        return out
    body = r.text or ""
    out["status"] = r.status_code
    out["bytes"] = len(body)
    out["secs"] = round(time.time() - t0, 2)
    out["server"] = r.headers.get("server", "")
    low = body.lower()
    out["markers"] = {m: (m.lower() in low) for m in X_MARKERS}
    out["body_exact"] = body.strip()[:40] if len(body) < 200 else None
    out["has_relay_script"] = None
    if out["markers"].get("relayRecords") and out["markers"].get("TBirdData"):
        from sources import xscrape
        script = xscrape.extract_relay_script(body)
        if script:
            tweets = xscrape.parse_relay_tweets(script, 8)
            out["relay_script_bytes"] = len(script)
            out["relay_tweets"] = len(tweets)
            out["has_relay_script"] = True
    return out


def run_x(start, count):
    users = _accounts()[start:start + count]
    data = _load(X_PROBE_PATH)
    with ThreadPoolExecutor(max_workers=len(users) or 1) as pool:
        futures = {pool.submit(probe_x, u): u for u in users}
        for fut in as_completed(futures):
            r = fut.result()
            data[r["account"]] = r
            print("@%-20s HTTP %-5s %7s bytes · %ss · relay=%s" % (
                r["account"], r.get("status"), r.get("bytes"),
                r.get("secs"), r.get("has_relay_script")))
    _save(X_PROBE_PATH, data)
    print("\nذخیره شد: %s (%d حساب)" % (X_PROBE_PATH, len(data)))


def print_x_summary():
    data = _load(X_PROBE_PATH)
    total = len(data)
    if not total:
        print("فایلی برای خلاصه نیست")
        return
    statuses = {}
    relay_ok = 0
    for r in data.values():
        statuses[str(r.get("status"))] = statuses.get(str(r.get("status")), 0) + 1
        if r.get("has_relay_script"):
            relay_ok += 1
    print("=== خلاصه‌ی کاوش x.com — %d حساب ===" % total)
    for k, v in sorted(statuses.items(), key=lambda x: -x[1]):
        print("  HTTP %-6s %d" % (k, v))
    print("  relay قابل پارس: %d" % relay_ok)
    sample = next(iter(data.values()))
    print("  نشانه‌ها (نمونه @%s): %s" % (sample["account"], sample.get("markers")))
# ------------------------------------------------ FxEmbed / FxTwitter API v2
def _fx_get(path, params=None, timeout=15, tries=3):
    """(status, json|None, latency, error) — هیچ‌وقت raise نمی‌کند.

    روی این شبکه درخواست‌ها گاهی RemoteDisconnected می‌دهند (بدون هیچ کد
    HTTP) — پس مثل مسیر x.com چند تلاش می‌کنیم.
    """
    t0 = time.time()
    url = FX_BASE + path
    err = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout,
                             headers={"User-Agent": UA})
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            print("   (retry %d %s -> %s)" % (i + 1, url, err[:60]))
            time.sleep(0.6 * (i + 1))
            continue
        lat = round(time.time() - t0, 2)
        if r.status_code == 204:
            return 204, None, lat, "no-content (since)"
        try:
            return r.status_code, r.json(), lat, None
        except Exception as e:
            return r.status_code, None, lat, "bad-json: %s (%r)" % (e, (r.text or "")[:80])
    return None, None, round(time.time() - t0, 2), err


def probe_fx(user, count=20):
    """یک حساب: profile + یک صفحه‌ی timeline (+ صفحه‌ی دوم برای pagination)."""
    out = {"account": user}
    st, prof, lat, err = _fx_get("/2/profile/%s" % user)
    out["profile_status"] = st
    out["profile_latency"] = lat
    out["profile_error"] = err
    if isinstance(prof, dict):
        u = prof.get("user") or {}
        out["resolved_name"] = u.get("name")
        out["resolved_id"] = u.get("id")
        out["followers"] = u.get("followers")

    st, page, lat, err = _fx_get("/2/profile/%s/statuses" % user,
                                 {"count": count})
    out["status"] = st
    out["latency"] = lat
    out["error"] = err
    results = []
    if isinstance(page, dict):
        out["code"] = page.get("code")
        results = page.get("results") or []
        out["cursor"] = bool((page.get("cursor") or {}).get("bottom"))
    out["tweets"] = len(results)
    if results:
        first = results[0]
        out["latest_id"] = first.get("id")
        out["latest_created_at"] = first.get("created_at")
        out["latest_text"] = (first.get("text") or "")[:120]
        out["tweet_fields"] = sorted(first.keys())
        kinds = {}
        media_kinds = set()
        quotes = 0
        for t in results:
            kinds[t.get("type")] = kinds.get(t.get("type"), 0) + 1
            med = (t.get("media") or {}).get("all") or []
            for m in med:
                media_kinds.add(m.get("type"))
            if t.get("quote"):
                quotes += 1
        out["types"] = kinds
        out["media_kinds"] = sorted(media_kinds)
        out["tweets_with_quote"] = quotes
        out["has_media_field"] = any((t.get("media") or {}).get("all") for t in results)
        out["with_video"] = "video" in media_kinds or "gif" in media_kinds
        # صفحه‌ی دوم — فقط برای یک حساب نمونه (هزینه‌ی اضافه)
        if out.get("cursor") and user == _accounts()[0]:
            cursor = (page.get("cursor") or {}).get("bottom")
            st2, page2, lat2, err2 = _fx_get("/2/profile/%s/statuses" % user,
                                             {"count": count, "cursor": cursor})
            res2 = (page2 or {}).get("results") or []
            out["page2_status"] = st2
            out["page2_tweets"] = len(res2)
            out["page2_latency"] = lat2
            out["page2_error"] = err2
            ids1 = {t.get("id") for t in results}
            ids2 = {t.get("id") for t in res2}
            out["page2_overlap"] = len(ids1 & ids2)
    return out


def run_fx(start, count, page_size=20, workers=6):
    users = _accounts()[start:start + count]
    data = _load(FX_PROBE_PATH)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(probe_fx, u, page_size): u for u in users}
        for fut in as_completed(futures):
            r = fut.result()
            data[r["account"]] = r
            # ذخیره‌ی تدریجی: اگر اجرا وسط راه قطع شد نتیجه‌ها از دست نروند
            _save(FX_PROBE_PATH, data)
            print("@%-20s HTTP %-5s tweets=%-3s media=%-4s quote=%-3s %ss %s" % (
                r["account"], r.get("status"), r.get("tweets"),
                r.get("has_media_field"), r.get("tweets_with_quote"),
                r.get("latency"), r.get("error") or ""), flush=True)
    _save(FX_PROBE_PATH, data)
    print("\nذخیره شد: %s (%d حساب)" % (FX_PROBE_PATH, len(data)))
def print_fx_summary():
    data = _load(FX_PROBE_PATH)
    ordered = [data.get(u) for u in _accounts()]
    rows = [r for r in ordered if r]
    if not rows:
        print("فایلی برای خلاصه نیست")
        return
    ok = [r for r in rows if r.get("status") == 200 and r.get("tweets")]
    print("=== خلاصه‌ی FxEmbed/FxTwitter — %d حساب ===" % len(rows))
    for r in rows:
        mark = "✓" if r in ok else "✗"
        print("%s @%-20s HTTP %-5s tweets=%-3s name=%s %s" % (
            mark, r["account"], r.get("status"), r.get("tweets"),
            r.get("resolved_name"), (r.get("error") or "")[:40]))
    print("\nموفق: %d   ناموفق: %d   نرخ: %.1f%%" % (
        len(ok), len(rows) - len(ok), 100.0 * len(ok) / len(rows)))
    lat = [r["latency"] for r in rows if r.get("latency")]
    if lat:
        print("latency: min %.2fs · max %.2fs · میانگین %.2fs" % (
            min(lat), max(lat), sum(lat) / len(lat)))
    with_media = sum(1 for r in ok if r.get("has_media_field"))
    with_quote = sum(1 for r in ok if r.get("tweets_with_quote"))
    with_video = sum(1 for r in ok if r.get("with_video"))
    total_tweets = sum(r.get("tweets") or 0 for r in ok)
    print("tweet های دریافتی (صفحه‌ی اول): %d" % total_tweets)
    print("حساب‌های با مدیا: %d · با ویدیو: %d · با quote: %d" % (
        with_media, with_video, with_quote))
    for r in ok[:2]:
        if r.get("page2_tweets") is not None:
            print("pagination @%s: صفحه۲=%s توییت · overlap=%s" % (
                r["account"], r.get("page2_tweets"), r.get("page2_overlap")))
        print("fields @%s: %s" % (r["account"], r.get("tweet_fields")))


# ----------------------------------------------------------------------- main
def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    start, count = 0, 5
    if "--start" in args:
        start = int(args[args.index("--start") + 1])
    if "--count" in args:
        count = int(args[args.index("--count") + 1])
    if cmd == "x":
        run_x(start, count)
    elif cmd == "x-summary":
        print_x_summary()
    elif cmd == "fx":
        run_fx(start, count)
    elif cmd == "fx-summary":
        print_fx_summary()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()