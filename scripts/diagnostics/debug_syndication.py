"""چرا لایه‌ی سندیکیشن جواب نداد؟ این را جایی بزن که اینترنت واقعی دارد.

وضعیت HTTP، هدرها، و اول چند خط پاسخ را خام چاپ می‌کند تا بفهمیم واقعاً
چرا جواب نداد (مسدود، خطای احراز هویت، قطعی شدن اتصال، یا چیز دیگر).
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import sys as _sys
import pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
import requests
import config

url = "https://cdn.syndication.twimg.com/timeline/profile"
headers = {
    "User-Agent": getattr(config, "USER_AGENT", "Mozilla/5.0"),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

for user in ("FabrizioRomano", "LFC"):
    print("=" * 60)
    print("تست @%s" % user)
    try:
        r = requests.get(
            url,
            params={"screen_name": user, "showReplies": "false"},
            headers=headers,
            timeout=10,
        )
        print("HTTP status:", r.status_code)
        print("content-type:", r.headers.get("content-type"))
        print("طول پاسخ:", len(r.text))
        print("۳۰۰ کاراکتر اول پاسخ:")
        print(r.text[:300])
    except Exception as e:
        print("خطا: %r" % e)
    print()
