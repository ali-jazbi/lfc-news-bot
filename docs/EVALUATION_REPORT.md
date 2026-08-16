# Real-Data Evaluation Report

اجرا: `python evaluate.py` روی **دیتابیس واقعی production** (۳۹ خبر ثبت‌شده).

## خلاصه

```
Total articles evaluated : 39  (sent_admin=30, new=8, rejected=1)

--- Hermes decision distribution (deterministic tier) ---
publish candidates : 23
review (human)     : 5
reject             : 11
tiers              : low=16, medium=19, high=4

--- Regression check vs old behavior ---
sent before, rejected now (false rejects) : 10
previously rejected, still rejected       : 1

--- Media coverage ---
items with image   : 31
items with video   : 3
items without image: 8

--- Translation quality (deterministic QC on stored translations) ---
no issues   : 17
with issues : 20

--- Golden-set accuracy (manual labels on real titles) ---
golden accuracy : 6/10
```

## یافته کلیدی: «false rejects» واقعاً مزخرف بوده‌اند

هر ۱۰ خبری که قبلاً به گروه ادمین رفته (sent_admin) و حالا تحلیل جدید رد
می‌کند، **واقعاً خبر لیورپول نبوده‌اند**:

- اورتون ×۲ (توافق با آرسنال)، نیوکاسل، امباپه، تون (سوئیس)، عذرخواهی شخصی،
  فیورنتینا/ژوائو ماریو، لواندوفسکی (شیکاگو فایر) ×۲

یعنی بات قبلی حدود **۳۳٪ پست‌های غیرمرتبط** را به ادمین می‌فرستاده
(حساب‌های TWITTER_LFC_ONLY فیلتر کلمه‌ای نمی‌خورند و اخبار تیم‌های دیگر
می‌دهند). این دقیقاً همان «خبر مزخرف» است که مأموریت می‌خواهد کم شود —
و در حالت هر دو (deterministic fallback و Hermes واقعی) گرفته می‌شود.

## محدودیت‌ها

1. **گلدن‌ست ۱۰تایی**: فقط با برچسب دستی روی عنوان‌ها ساخته شده — نمونهٔ کوچک
   و ناقص است (در DB فقط ۳۹ خبر هست، نه ۵۰-۱۰۰). برای دقت آماری باید چند
   هفته دادهٔ جدید جمع شود.
2. **تخمین کیفیت ترجمه ۱۷/۳۷**: چک قطعی QC (اعداد/نام/طول متن) روی ترجمه‌های
   ذخیره‌شدهٔ قبلی. بخشی از «issues» احتمالاً مثبت کاذب چکِ سخت‌گیرانه است
   (مثلاً عدد سال که عمداً ننوشته‌اند) — برای تأیید، نمونه باید انسانی بازبینی شود.
3. **این ارزیابی از تحلیل قطعی استفاده می‌کند** (هزینه صفر). تحلیل واقعی
   Hermes در تست end-to-end جداگانه نشان داد ادعای نقل‌وانتقال را درست
   طبقه‌بندی می‌کند و با شواهد وب (اختلاف قیمت) آن را می‌سنجد — اما اجرای
   دسته‌ای روی ۳۹ خبر هزینهٔ توکن دارد و عمداً در این گزارش انجام نشد.
4. **Importance accuracy**: با قواعد قطعی (official/breaking/priority → 8-9)
   محاسبه می‌شود؛ دقت عددی ۱-۱۰ نیاز به بازبینی انسانی نمونه‌ای دارد.

## چه چیزی باید بعداً اندازه گرفته شود

- بعد از یک ماه اجرا با HERMES_ENABLED=true: نسبت publish/review/reject واقعی
  و مقایسه با «Human: reject» (جدول feedback) — حلقه بازخورد مرحله ۱۲.
- دقت عکس: چند درصد خبرِ بدون عکس با اطمینان بالا عکس گرفت و چند درصد
  عمداً بدون عکس ماند (هرگز عکس تصادفی).
- نرخ از دست‌رفتن خبر (retry_pending → failed) بعد از فعال‌شدن pipeline.
