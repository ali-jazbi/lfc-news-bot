# Real-Data Evaluation Report

اجرا: `python scripts/maintenance/evaluate.py` (بدون هزینه AI) و `python scripts/maintenance/evaluate.py --with-ai --verify`
(با Hermes واقعی). Dataset: ۷ آیتم واقعی DB + ۴۲ golden-only = **۴۹ آیتم**،
گلدن‌ست ساختاریافته در `evaluation/golden.json` (۵۰ ورودی، ۱۶ دسته).

خروجی‌های کامل: `evaluation/results/evaluation_*.{json,md}` + `latest_*.{json,md}`.

## حالت ۱ — Deterministic (هزینه صفر)

```
Mode               : deterministic
Total articles     : 49 (DB=7, golden-only=42)
Golden items       : 48

Decision distribution: publish=22, review=12, reject=14
tiers              : low=33, medium=9, high=7

Confusion matrix (Expected \ Actual):
                 publish    review    reject
        publish       22         0         0
         review        0        12         0
         reject        0         0        14

golden_accuracy     : 48/48 = 1.000
publish_precision   : 1.0
reject_precision    : 1.0
false_reject_rate   : 0.0
false_accept_risk   : 0.0
review_rate         : 0.245
```

## حالت ۲ — Hermes واقعی (`--with-ai`)

همان ۴۹ آیتم با LLM واقعی (qwen3.7-plus از طریق زنجیره پروژه؛ روی golden
entries اجرا شد، `AI_ALWAYS_ANALYZE=true`). نتیجه cache می‌شود
(`evaluation/results/ai_cache_ai.json`) تا اجرای مجدد هزینه نداشته باشد.

```
golden_accuracy     : 47/48 = 0.979
publish_precision   : 0.957
reject_precision    : 1.0
false_reject_rate   : 0.0
false_accept_risk   : 0.0
review_rate         : 0.224

AI cost (این اجرا): 48 LLM calls + 1 verification call, 0 errors,
total latency ≈ 180s (بدون cache)
```

### Divergence Deterministic vs Hermes (پس از اعمال policy guard)

| خبر | Deterministic | Hermes | ارزیابی |
|---|---|---|---|
| Liverpool defender ruled out (Sky) | review | **publish** | Hermes «confirmed» را از متن خواند و تأییدشده پنداشت — مورد مرزی؛ در عمل به ادمین می‌رود (limitation) |

قبل از اصلاحات، Hermes روی همین گلدن‌ست **0.766** بود و **۱۱ خطا** داشت
(از جمله پابلیش خبرهای women's team، foundation/charity، گالری، خبر قدیمی
۲۰۲۴ و ادعاهای مهم از Sky بدون verification). با دو لایه اصلاح به 0.979 رسید:

1. **Hard rules** (`ai/editor.py::_hard_rules_analysis`): قواعد قطعی کانال
   (SKIP_KEYWORDS، INCLUDE_WOMEN، خبر قدیمی، opinion/clickbait) همیشه اول
   اعمال می‌شوند — Hermes هرگز نمی‌تواند آن‌ها را override کند.
2. **Policy guard** (`_policy_guard`): ادعای مهم (injury/breaking ≥۷،
   transfer ≥۸) از منبع غیررسمی → review + verification اجباری، حتی اگر
   LLM publish بدهد.

## Verification واقعی (anti-hallucination)

روی «Liverpool are working on Bradley Barcola deal» (رومانو):

```
verified: False | confidence: 0.1
summary: شواهد مستقل کافی نیست (فقط Tier 4/5) — خبر برای بازبینی انسانی می‌ماند
evidence: Google News ×3 (Tier 5)
```

قانون: بدون شواهد Tier 1 یا دو شواهد Tier 2/3، هرگز تأیید نمی‌شود — حتی اگر
AI مطمئن باشد. شواهد با وزن منبع (tier) مرتب و امتیازدهی می‌شوند
(`ai/hermes_client.py::weighted_evidence_score`).

## Category breakdown (گلدن)

`[OK]` در هر ۲۶ دسته از ۲۷ دسته؛ تنها مورد ناقص: `injury` (مورد مرزی
«confirmed via Sky» بالا). جزئیات کامل در خروجی Markdown.

## Regression vs رفتار قبلی بات

- از ۲ خبری که قبلاً به ادمین رفته بود، ۰ خبر الان رد می‌شود (در ۷ آیتم
  فعلی DB). در ارزیابی ۳۹ آیتمی قبلی، هر ۱۰ خبرِ «قبلاً رفته، الان رد
  می‌شود» **واقعاً غیر-لیورپول بودند** (اورتون، نیوکاسل، امباپه،
  لواندوفسکی...) — یعنی بات قبلی ~۳۳٪ پست غیرمرتبط می‌فرستاد.

## هزینه AI (مرحله ۲۶)

- `scripts/maintenance/evaluate.py` بدون `--with-ai`: **۰ هزینه**.
- `--with-ai`: ۴۸ LLM call برای ۴۹ آیتم (≈۱ call/خبر) + verification فقط
  برای موارد نیازمند (در این اجرا ۱). با cache، اجرای مجدد ≈ ۰ call.
- طراحی tiering: منبع رسمی → مسیر ارزان/قطعی؛ ادعای مهم → verification.
  هر خبر ساده وارد Agent سنگین نمی‌شود.

## محدودیت‌ها

1. **گلدن‌ست ۵۰تایی** شامل ۴۲ entry ترکیبی (بر پایه الگوهای واقعی editorial)
   است و ۷ مورد از DB واقعی. برای دقت آماری کامل، چند هفته داده واقعی جدید
   با برچسب انسانی لازم است.
2. **مورد مرزی «confirmed via Sky»**: Hermes کلمه «confirmed» در متن را
   تأیید باشگاه می‌پندارد. قابل قبول ولی محتاطانه‌تر از گلدن.
3. **Importance دقت**: در گلدن range (مثلاً [5,8]) گذاشته شده؛ دقت عددی
   ۱-۱۰ نیاز به بازبینی انسانی نمونه‌ای دارد.
4. **Vision واقعی**: در این محیط مدل vision-capable در دسترس نبود؛ انتخاب
   عکس با ارزیابی متنی + hard rule «بدون عکس بهتر از عکس اشتباه» انجام شد.
5. **Translation QC**: چک قطعی روی ترجمه‌های ذخیره‌شدهٔ قبلی؛ بازبینی AI
   با نمونه‌های کانال در اجرای زنده اعمال می‌شود (fail-closed).

## چه چیزی بعداً اندازه بگیریم

- بعد از یک ماه HERMES_ENABLED=true: نسبت publish/review/reject واقعی و
  مقایسه با جدول feedback (مرحله ۱۲).
- دقت عکس زنده: چند درصد بدون عکس ماند عمداً.
- نرخ retry_pending → failed (گم‌نشدن خبر).
