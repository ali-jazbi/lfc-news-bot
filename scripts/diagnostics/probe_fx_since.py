"""بررسی since/204 در FxTwitter + علت 404 حساب‌های خاص.

    python scripts/diagnostics/probe_fx_since.py
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


def get(path, params=None, tries=4):
    for i in range(tries):
        try:
            return requests.get(BASE + path, params=params, timeout=20,
                                headers={"User-Agent": UA})
        except Exception as e:
            print("   retry %d %s: %s" % (i + 1, path, type(e).__name__), flush=True)
            time.sleep(1.0 * (i + 1))
    return None


now = int(time.time())
_which = sys.argv[1] if len(sys.argv) > 1 else "since"

if _which == "since":
    print("=== since (ثانیه/میلی‌ثانیه) ===", flush=True)
    for label, params in (
            ("since=now-1h", {"count": 20, "since": now - 3600}),
            ("since=now+1h", {"count": 20, "since": now + 3600}),
    ):
        r = get("/2/profile/FabrizioRomano/statuses", params, tries=3)
        n = None
        msg = None
        if r is not None and r.status_code == 200:
            try:
                n = len((r.json().get("results") or []))
            except Exception:
                pass
        if r is not None:
            try:
                msg = r.json().get("message")
            except Exception:
                pass
        print("  %-14s → HTTP %-4s tweets=%-4s msg=%s" % (
            label, r.status_code if r else None, n, msg), flush=True)
    r = get("/2/profile/FabrizioRomano/statuses",
            {"count": 20, "since": (now - 3600) * 1000}, tries=3)
    print("  since=ms       → HTTP %s" % (r.status_code if r else None), flush=True)
    sys.exit(0)

if _which == "404":
    print("=== حساب‌های 404 ===", flush=True)
    for h in ("AnfieldSector", "Anfieldmedia_", "LiverpoolFF", "mnstr_mntlt"):
        rp = get("/2/profile/%s" % h, tries=3)
        prof = {}
        try:
            prof = rp.json()
        except Exception:
            pass
        rs = get("/2/profile/%s/statuses" % h, {"count": 5}, tries=3)
        sbody = {}
        try:
            sbody = rs.json()
        except Exception:
            pass
        print("  @%-16s profile HTTP %-5s code=%-5s msg=%-30s | statuses HTTP %-5s code=%-5s msg=%s"
              % (h, rp.status_code if rp else None, prof.get("code"),
                 prof.get("message"), rs.status_code if rs else None,
                 sbody.get("code"), sbody.get("message")), flush=True)
        if prof.get("user"):
            print("      کاربر واقعی: %s (@%s) protected=%s" % (
                prof["user"].get("name"), prof["user"].get("screen_name"),
                prof["user"].get("protected")), flush=True)
    sys.exit(0)

print("=== typeahead ===", flush=True)
for h in ("AnfieldSector", "Anfieldmedia_", "LiverpoolFF", "mnstr_mntlt"):
    r = get("/2/typeahead", {"q": h}, tries=3)
    body = {}
    try:
        body = r.json()
    except Exception:
        pass
    users = body.get("users") or body.get("results") or []
    names = [(u.get("screen_name"), u.get("name")) for u in users[:4]]
    print("  %-16s HTTP %s → %s" % (h, r.status_code if r else None, names), flush=True)