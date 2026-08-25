---
type: Decision
date: 2026-08-23
engine: claude-code
status: accepted
tags: [twitter, xscrape, nitter, feature]
relations:
  supersedes: null
---

# Decision — جایگزینی نیتر با اسکرپ مستقیم x.com (`TWITTER_MODE=xscrape`)

## زمینه

همهٔ آینه‌های نیتر در پروداکشن مرده بودند (`no healthy mirror found`، هزاران شکست پیاپی) — منبع توییتر بات عملاً خاموش. مالک خواست روشی مثل دانلودر تلگرامی (@twittervid_bot) شود؛ آنالیز نشان داد Bot API اجازهٔ بات→بات نمی‌دهد و بات مرجع (D:\Github\Liverpool-bot) در واقع HTML سایت x.com را اسکرپ می‌کند.

## تصمیم

- فلگ واحد `TWITTER_MODE`: `classic` (پیش‌فرض = مسیر نیتر دست‌نخورده) | `xscrape` (اسکرپ مستقیم x.com)
- ماژول جدید `sources/xscrape.py` — پورت relay-record parser از Liverpool-bot؛ خروجی با قرارداد entry نیتر سازگار تا پایپ‌لاین تغییر نکند
- ویدیو: mp4 اسکرپی → fallback به fxtwitter/vxtwitter از طریق funnel جدید `resolve_video()` — نقطهٔ اتصال آیندهٔ twittervid_bot (نیاز به Telethon + سشن کاربر؛ اسکلت تست: scripts/manual_tests/test_twittervid_bot.py)
- اگر x.com چند سیکل مرده → برگشت خودکار به نیتر (`XSCRAPE_FALLBACK_CLASSIC=true`)
- main.py هیچ تغییری نکرد

## اعتبارسنجی

- ۱۶ تست شبکه‌ای جدید + ۱۲۳ تست قبلی: پاس
- تست واقعی با اینترنت: ۲۸/۲۹ حساب روی سرور، ۵ پست توییتری در اولین سیکل منتشر شد

## Next

- مانیتور نرخ موفقیت xscrape روی IP دیتاسنتر (ریسک بلاک X)
- مالک هنوز جوین اسپانسر twittervid_bot را تست نکرده — فقط در صورت مرگ xscrape/fxtwitter ارزش پیگیری دارد
- ارور Gemini 403 در ترجمه (fallback به qwen کار می‌کند ولی هر ترجمه ~۸ ثانیه اضافه طول می‌کشد) — بررسی کلید/endpoint
- ۲ تست قدیمی خراب tests/test_qc_fail_closed.py — بی‌ربط به این تغییرات، بررسی شود
