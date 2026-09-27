"""قرارداد دقیق FxTwitter API v2 — ساختار media/video/quote + رفتار since/204.

خروجی JSON خام را در logs/ ذخیره می‌کند تا mapper روی ساختار واقعی (نه
حدسی) نوشته شود. هیچ credential/Cookie لازم نیست.

    python scripts/diagnostics/probe_fx_contract.py
"""
import json
import os
import pathlib as _pathlib
import sys
import time

_root = str(_pathlib.Path(__file__).resolve().parents[2])
sys.path.insert(0, _root)
os.chdir(_root)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
BASE = "https://api.fxtwitter.com"


def get(path, params=None, tries=3):
    for i in range(tries):
        try:
            r = requests.get(BASE + path, params=params, timeout=20,
                             headers={"User-Agent": UA})
            return r
        except Exception as e:
            print("  retry %d %s: %s" % (i + 1, path, type(e).__name__))
            time.sleep(0.8 * (i + 1))
    return None


def dump(name, obj):
    p = os.path.join("logs", name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    print("  ذخیره شد %s" % p)


print("=== ۱) صفحه‌ی timeline یک حساب پرترافیک ===")
r = get("/2/profile/FabrizioRomano/statuses", {"count": 20})
page1 = r.json()
dump("fx_page1.json", page1)
print("  HTTP", r.status_code, "توییت:", len(page1.get("results") or []))

print("\n=== ۲) ساختار media یک توییت ویدیویی ===")
vid = next((t for t in page1["results"]
            if any(m.get("type") == "video" for m in
                   ((t.get("media") or {}).get("all") or []))), None)
if vid is None:
    # از حساب‌های ویدیو-محور بگیر
    r2 = get("/2/profile/LFC/statuses", {"count": 20})
    p2 = r2.json()
    dump("fx_page_lfc.json", p2)
    vid = next((t for t in (p2.get("results") or [])
                if any(m.get("type") == "video" for m in
                       ((t.get("media") or {}).get("all") or []))), None)
if vid:
    print("  توییت:", vid.get("url"))
    print("  media keys:", sorted((vid.get("media") or {}).keys()))
    print("  media.all types:", [m.get("type") for m in (vid.get("media") or {}).get("all", [])])
    dump("fx_video_tweet.json", vid)
    print("  media JSON:", json.dumps(vid.get("media"), ensure_ascii=False)[:800])
else:
    print("  ویدیو در صفحه‌های نمونه پیدا نشد")

print("\n=== ۳) ساختار quote ===")
q = next((t for t in page1["results"] if t.get("quote")), None)
if q:
    print("  توییت:", q.get("url"))
    print("  quote keys:", sorted((q.get("quote") or {}).keys()))
    print("  quote.author:", json.dumps((q["quote"].get("author") or {}), ensure_ascii=False)[:200])
    dump("fx_quote_tweet.json", q)
else:
    print("  quote در صفحه‌ی نمونه پیدا نشد")

print("\n=== ۴) ساختار embed_card / card ===")
c = next((t for t in page1["results"] if t.get("embed_card") or t.get("card")), None)
if c:
    print("  توییت:", c.get("url"))
    print("  embed_card:", json.dumps(c.get("embed_card"), ensure_ascii=False)[:400])
    print("  card:", json.dumps(c.get("card"), ensure_ascii=False)[:400])
else:
    print("  کارت لینک در صفحه‌ی نمونه نبود")

print("\n=== ۵) رفتار since (incremental polling) ===")
now = int(time.time())
r = get("/2/profile/FabrizioRomano/statuses", {"count": 20, "since": now - 3600})
if r is not None:
    body = r.json() if r.status_code == 200 else None
    print("  since=اکنون-۱ساعت → HTTP %s · توییت %s" % (
        r.status_code, len((body or {}).get("results") or []) if body else "-"))
r = get("/2/profile/FabrizioRomano/statuses", {"count": 20, "since": now + 3600})
print("  since=اکنون+۱ساعت → HTTP %s (انتظار 204)" % (r.status_code if r else None))
r = get("/2/profile/FabrizioRomano/statuses",
        {"count": 20, "since": (now - 3600) * 1000})
print("  since با میلی‌ثانیه → HTTP %s" % (r.status_code if r else None))

print("\n=== ۶) حساب‌هایی که statuses شان 404 داد ===")
for h in ("DataAnalyticEPL", "AnfieldSector", "Anfieldmedia_", "LiverpoolFF", "mnstr_mntlt"):
    rp = get("/2/profile/%s" % h)
    prof = None
    try:
        prof = rp.json()
    except Exception:
        pass
    u = (prof or {}).get("user") or {}
    rs = get("/2/profile/%s/statuses" % h, {"count": 5})
    msg = None
    try:
        msg = rs.json().get("message")
    except Exception:
        pass
    print("  @%-18s profile HTTP %s (name=%s) · statuses HTTP %s · msg=%s" % (
        h, rp.status_code if rp else None, u.get("name"),
        rs.status_code if rs else None, msg))

print("\n=== ۷) /2/status/{id} برای لینک توییت ادمین ===")
tid = page1["results"][0]["id"]
r = get("/2/status/%s" % tid)
one = r.json()
dump("fx_single_status.json", one)
print("  HTTP %s · status keys: %s" % (r.status_code, sorted((one.get("status") or {}).keys())[:12]))
print("  type:", (one.get("status") or {}).get("type"))