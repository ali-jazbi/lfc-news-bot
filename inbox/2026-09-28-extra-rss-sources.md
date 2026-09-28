---
type: Decision
engine: claude
date: 2026-09-28
status: accepted
tags: [rss, sources, outlet_rss, config]
relations:
  extends: /inbox/2026-09-27-fxembed-twitter-source.md
---

# Decision — کاتالوگ منابع RSS جدید و اختیاری (`OUTLET_RSS_SOURCES`)

## تصمیم

- ۴ فید «فقط لیورپول» که مالک روی سیستم خودش با `parse_rss` تست کرد
  (Football365: ۲۵، Liverpool.com: ۲۵، Guardian: ۲۰، This Is Anfield: ۱۶ آیتم)
  در `sources/outlet_rss.py` → `CATALOG` ثبت شدند.
- فعال‌سازی فقط با `OUTLET_RSS_SOURCES` در `.env` (پیش‌فرض خالی = هیچ تغییری).
  شناسه‌ها: `football365, liverpoolcom, guardian, thisisanfield` یا `all`.
- مسیر جدا: تابع `fetch_extra()` و منبع `rss_extra` در `main._sources()`، **آخر لیست**
  (بعد از توییتر). `fetch()` قدیمی، فید BBC و `OUTLET_RSS_FEEDS` دست‌نخورده‌اند.

## چرا مسیر جدا (و نه افزودن به OUTLET_RSS_FEEDS)

- `fetch()` قدیمی سقف `limit` را **بین همه‌ی فیدها مشترک** می‌گیرد؛ فید BBC (~۲۰+ آیتم)
  همان اول سقف را پر می‌کند و فیدهای بعدی هیچ‌وقت خوانده نمی‌شدند.
- `fetch_extra()` برای هر منبع سقف جدا دارد.
- سلامت/backoff منبع `rss_extra` مستقل از `outlet_rss` قدیمی است.
- آخر لیست بودن: `run_cycle` سقف آیتم هر سیکل دارد؛ خبر توییتر نباید عقب بیفتد.

## فیلتر سن (`OUTLET_RSS_MAX_AGE_HOURS`، پیش‌فرض ۱۲)

روشن‌کردن یک منبع تازه بدون فیلتر، ۲۰–۲۵ خبر چندروزه را به گروه می‌ریخت.
تاریخ خالی یا نامعتبر = نگه‌دار (خبر به‌خاطر فرمت تاریخ گم نشود). `0` = خاموش.

## فیلتر کلمه

هر ۴ فید اختصاصی لیورپول‌اند؛ `RELEVANCE_KEYWORDS` روی آن‌ها اعمال نمی‌شود
(مثلاً خبر «Konate fitness doubt» بدون کلمه‌ی liverpool نباید حذف شود).

## اعتبارسنجی

- `tests/test_outlet_rss_extra.py` — ۱۳ تست بدون شبکه (FAIL: ۱۲ → PASS: ۱۳).
- کل `tests/`: ۲۶۱ pass (پایه ۲۴۸ + ۱۳ جدید)، بدون رگرسیون.
- بررسی end-to-end با feedparser واقعی روی XML نمونه (بدون شبکه): فیلتر سن و نام منبع درست.
- **انجام نشد:** اجرای زنده‌ی `main.py --once --dry-run` روی فیدهای واقعی (سندباکس دسترسی نداشت).

## Next

- اجرای `python main.py --once --dry-run` با `OUTLET_RSS_SOURCES=guardian` روی سیستم مالک.
- فیدهای تست‌نشده‌ی دیگر (The Athletic، Daily Mail، Anfield Watch، ...) بعد از تست دستی
  به `CATALOG` اضافه شوند.
- `_team_specific()` قدیمی هر URL حاوی «liverpool» را اختصاصی می‌داند
  (مثلاً `liverpoolecho.co.uk/rss.xml` که کل مرسی‌ساید است) — عمداً دست نخورد.
