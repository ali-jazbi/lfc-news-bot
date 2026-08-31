---
type: Session
engine: cline
date: 2026-08-31
---

# Session — رفع ۴ باگ از دست رفتن خبر در حالت xscrape

## Done
- **باگ ۱ (فیلتر کلیدواژه):** `ROMANO_KEYWORDS` گسترش یافت (اسکواد فعلی + ایرائولا
  به‌جای اسلوتِ stale + نام‌های رایج باشگاه). `curtis jones`/`harvey elliott`
  عمداً فول‌نیم‌اند (false positive اسامی تنها). امضای `_is_relevant` حالا
  `quoted_text` هم می‌گیرد؛ در `_fetch_xscrape` و `_fetch_classic` اول نقل‌قول
  استخراج می‌شود بعد چک relevance. ⚠ لیست تاریخ‌مصرف‌دار — قبل از هر پنجرهٔ
  نقل‌وانتقالاتی بازبینی شود (کامنت در config.py نوشته شد).
- **باگ ۲ (سقف [:3]):** سقف هاردکد حذف شد؛ متغیر جدید
  `TWEETS_CHECKED_PER_ACCOUNT_PER_CYCLE` (پیش‌فرض ۸) در هر دو مسیر xscrape و
  classic. در .env.example هم اضافه شد.
- **باگ ۳ (scrape_user بدون retry):** تابع مشترک `_fetch_html(url, tries)`
  (درخواست تازه بدون کوکی در هر تلاش) ساخته شد؛ `fetch_tweet` و `scrape_user`
  هر دو از آن می‌روند. `fetch_page` (تک‌شات session کوکی‌دار) فقط برای سازگاری
  مانده و دیگر در مسیر اصلی نیست. تست زندهٔ همین سشن: 28/29 حساب جواب داد.
- **باگ ۴ (note_tweet):** ساختار relay کشف شد (لینک واقعی
  sean_rogers/status/2094056601925640651):
  `client:<b64>:note_tweet → NoteTweetResults → result → text`. تابع
  `extract_note_tweet_text` در `parse_relay_tweets` و `extract_quoted_tweet`
  وقتی متن بلندتری دارد جایگزین `full_text` می‌شود (fallback حفظ شده). تست
  زنده: ۱۴۳۵ کاراکتر کامل به‌جای ۳۱۷ کاراکتر کوتاه‌شده.
- پروتکل TDD برای هر ۴ باگ: اول تست FAIL روی کد قدیمی، بعد فیکس، بعد PASS.
- کل سوییت: ۱۶۱ پاس (۱۵۰ قدیمی + ۱۱ جدید)، صفر رگرسیون.
- `python main.py --once --dry-run`: پایپ‌لاین کامل سالم (xscrape: 28/29 حساب،
  14 item جمع‌آوری، ترجمه و فرمت بدون خطا).

## Decided
- در انتخاب متن، «طولانی‌تر برنده است» — note_tweet فقط وقتی جایگزین می‌شود که
  از full_text بلندتر باشد؛ full_text حذف نشد (اکثر توییت‌ها note_tweet ندارند).
- تست‌های قدیمی session-محور (http_500/network_error/no_relay_data) به مسیر
  requests.get + retry منتقل شدند؛ `_session` در تست‌ها با raise مسدود می‌شود تا
  اگر روزی مسیر قدیمی برگشت، تست‌ها بدون شبکه شکست بخورند.

## Next
- بازبینی `ROMANO_KEYWORDS` قبل از پنجرهٔ نقل‌وانتقالاتی زمستان (اول ژانویه).
- اگر x.com روزی فرمت relay را عوض کند، اول `_note_script` ساختار را چک کند.
