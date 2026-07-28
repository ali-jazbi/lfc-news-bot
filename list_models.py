"""لیست مدل‌های قابل استفاده با کلید تو — python list_models.py [llm1]

یک کلید داری و ده‌ها مدل؛ این اسکریپت می‌گوید دقیقاً چه نام‌هایی مجازند،
تا مجبور نشوی حدس بزنی و خطای 404 بگیری.
خروجیش را مستقیم در LLMx_MODEL کپی کن.
"""
import sys

import requests

import config

proxies = {"http": config.PROXY, "https": config.PROXY} if config.PROXY else None


def main():
    slot = (sys.argv[1] if len(sys.argv) > 1 else "llm1").lower()
    cfg = config.LLM_SLOTS.get(slot)
    if not cfg:
        print("اسلات نامعتبر. مجاز: " + ", ".join(config.LLM_SLOTS))
        sys.exit(1)
    if not cfg["base_url"] or not cfg["key"]:
        print(f"اسلات {slot} در .env پر نشده (به LLMₓ_BASE_URL و LLMₓ_KEY نیاز دارد).")
        sys.exit(1)

    url = cfg["base_url"].rstrip("/") + "/models"
    print(f"درخواست به: {url}\n")

    try:
        r = requests.get(
            url,
            headers={"Authorization": "Bearer " + cfg["key"]},
            timeout=40,
            proxies=proxies,
        )
    except Exception as e:
        print(f"❌ اتصال برقرار نشد: {type(e).__name__} — {e}")
        sys.exit(1)

    if r.status_code != 200:
        print(f"❌ HTTP {r.status_code}\n{r.text[:400]}")
        sys.exit(1)

    data = r.json()
    models = data.get("data") if isinstance(data, dict) else data
    if not models:
        print("پاسخ خالی بود:\n" + str(data)[:400])
        sys.exit(1)

    free, paid = [], []
    for m in models:
        mid = m.get("id") if isinstance(m, dict) else str(m)
        if not mid:
            continue
        (free if "free" in mid.lower() else paid).append(mid)

    if free:
        print("\u2500" * 55)
        print(f"رایگان ({len(free)} مدل) — این‌ها را اول امتحان کن:")
        print("\u2500" * 55)
        for mid in sorted(free):
            print("  " + mid)

    print("\n" + "\u2500" * 55)
    print(f"بقیه ({len(paid)} مدل)")
    print("\u2500" * 55)
    for mid in sorted(paid):
        print("  " + mid)

    print(f"\nجمع: {len(free) + len(paid)} مدل")
    print("یکی را انتخاب کن و در .env بگذار، مثلاً:")
    example = (sorted(free) or sorted(paid))[0]
    print(f"  {slot.upper()}_MODEL={example}")


if __name__ == "__main__":
    main()
