---
type: Decision
engine: cline
date: 2026-09-27
status: accepted
tags: [twitter, xscrape, fxembed, fxtwitter, nitter, source]
relations:
  supersedes: 2026-08-23-xscrape-feature
---

# Decision — منبع توییتر جدید: `TWITTER_MODE=fxembed` (FxEmbed/FxTwitter API v2)

## زمینه: چه چیزی خراب شد

- `xscrape` (اسکرپ HTML صفحه‌ی x.com) از اواسط سپتامبر ۲۰۲۶ برای **همه‌ی ۲۹ حساب**
  صفر نتیجه می‌داد.
- تست مستقیم همین سشن (۲۹ درخواست خام، بدون لایه‌ی بات — `scripts/diagnostics/probe_sources.py x`):
  - بخشی از درخواست‌ها `HTTP 403` با بدنه‌ی دقیقاً `IPv6` از Cloudflare (مشکل شبکه/IP).
  - بقیه `HTTP 200` با HTML واقعی (۱۶۴–۱۹۲ کیلوبایت) ولی **بدون `relayRecords`
    و بدون `TBirdData`** → `extract_relay_script()` همیشه `None` می‌دهد.
  - در همان HTML فقط رشته‌های `graphql` و `UserByScreenName` پیدا شد؛ یعنی
    صفحه یک **shell** است و داده از API داخلی X (GraphQL) می‌آید، نه SSR.
- نتیجه: فرضیه‌ی قبلی پروژه (داده‌ی توییت داخل HTML اولیه embed شده) **رد شد**.
  این یک تغییر ساختاری سمت X است، نه بلاک IP و نه مشکل کوکی/لاگین
  (لاگین با `auth_token`/`ct0`/`cf_clearance` هم تفاوتی نداد و قبلاً هم ~۵۰٪ شکست داشت).


## چه راه‌حل‌هایی بررسی شدند

| گزینه | نتیجه‌ی بررسی واقعی |
|---|---|
| `xscrape` (HTML/relay) | مرده — داده در HTML نیست (۲۰۰ با HTML، صفر relay) |
| classic/Nitter | مرده — آینه‌ها در پروداکشن جواب نمی‌دهند (قبلاً هم همین دلیل xscrape ساخته شد) |
| سندیکیشن توییتر (`cdn.syndication.twimg.com`) | از قبل خاموش است (HTTP 200 با بدنه‌ی خالی = بلاک بی‌صدا) |
| GraphQL داخلی X (`UserByScreenName`/`UserTweets`) | **لازم نشد.** تأیید شد که داده از API داخلی می‌آید، ولی این مسیر نیاز به توکن/کوکی و هدر `x-csrf-token` و تعقیب مداوم `queryId`های X دارد — نگهداری‌پذیری ضعیف |
| **FxEmbed / FxTwitter API v2** (`api.fxtwitter.com`) | **کار کرد** — رایگان، بدون API key، بدون Cookie، بدون لاگین، OpenAPI رسمی |

## تصمیم

- منبع جدید و توصیه‌شده: `TWITTER_MODE=fxembed` — ماژول جدید `sources/fxembed.py`
  که `api.fxtwitter.com/2/profile/{handle}/statuses` را می‌خواند و خروجی را به
  **همان قرارداد entry** نیتر/xscrape تبدیل می‌کند:
  `title, link, summary, image, published` + دو side-channel
  `_xscrape_media` و `_xscrape_quoted`.
- به همین دلیل `translate.py`، `formatter.py`، منطق تلگرام و `main.py` **هیچ تغییری
  نکردند**؛ `_attach_media`/`build_tweet_item`/`_entries_to_items` همان‌ها را می‌خوانند.
- حالت‌های قبلی دست‌نخورده ماندند: `TWITTER_MODE=xscrape` و `TWITTER_MODE=classic`
  هر دو همچنان کار می‌کنند (فقط مستند شد که xscrape مرده و classic/Nitter
  legacy/غیرقابل‌اتکا است).
- لینک خام ادمین (`item_from_url`) هم بر اساس حالت انتخاب می‌کند: در fxembed از
  `GET /2/status/{id}` می‌آید.
- هیچ secret/Cookie/API key ای اضافه نشد — این API به هیچ‌کدام نیاز ندارد.

## اعتبارسنجی (اعداد واقعی، نه mock)

۱) کاوش خام API روی **۲۹ حساب واقعی پروژه** (`probe_sources.py fx`):
`HTTP` سالم، هر صفحه ۱۷–۲۱ توییت، pagination با cursor سالم (صفحه‌ی دوم: ۱۹ توییت،
overlap=۰)، latency ۰٫۹–۱۹ ثانیه.

۲) از **مسیر خودِ بات** (`scripts/manual_tests/test_fxembed.py` → `fxembed.scrape_user`)
**دو اجرای کامل روی ۲۹ حساب واقعی**:

```text
اجرای ۱:  29 accounts · موفق 27 · ناموفق 2 · نرخ 93.1% · 524 توییت
           حساب با مدیا: 24 · با ویدیو: 11 · با نقل‌قول: 23
اجرای ۲:  29 accounts · موفق 26 · ناموفق 3 · نرخ 89.7% · 508 توییت
           حساب با مدیا: 23 · با ویدیو: 10 · با نقل‌قول: 22
```

دو حساب `@AnfieldSector` و `@Anfieldmedia_` در هر دو اجرا **ساسپند** هستند
(پاسخ API: `User is suspended`) و هیچ منبعی نمی‌تواند خبرشان را بیاورد.
سومین ناموفقی در اجرای ۲ (`@LiverpoolFF`) **خطای گذرای شبکه** بود، نه حساب:
بلافاصله بعد، ۴ بار پشت‌سرهم `۴/۴` موفق با ۲۰ توییت (۵–۱۰ ثانیه هر بار) — چون
همان لحظه `RemoteDisconnected`/`ReadTimeout` روی کل شبکه می‌خورد. برای همین
`FXEMBED_FETCH_TRIES=3` با backoff گذاشته شده و اگر باز هم نشد، سیکل بعد دوباره
تلاش می‌کند (همان رفتار موجود سیستم برای هر منبع).

۳) تست‌های واحد بدون شبکه: `tests/test_fxembed.py` — **۲۸ تست**، پروتکل
FAIL→FIX→PASS (اول ۲۷ تست FAIL چون ماژول وجود نداشت، بعد از پیاده‌سازی ۲۸ PASS).
کل سوییت: **۲۳۶ تست PASS**، صفر رگرسیون.

۴) `python main.py --once --dry-run` با `TWITTER_MODE=fxembed` روی ۲۹ حساب واقعی،
**دو بار** و هر دو بار بدون خطا/Traceback تمام شد:

```text
اجرای ۱:  src.twitter | fxembed: 27/29 accounts in 51.4s
          main | collected 9 items → sent 5 item(s) this cycle
اجرای ۲:  src.twitter | fxembed: 27/29 accounts in 49.2s
          main | collected 9 items → sent 2 item(s) this cycle  (تکراری‌ها در DB دیده شد)
```

مترجم روی چند آیتم خطای اتصال LLM داد (مشکل شبکه‌ی ارائه‌دهنده) و زنجیره‌ی
fallback ترجمه مثل قبل کار کرد — یعنی این سمت اصلاً ربطی به منبع جدید ندارد.

## نکات عملیاتی که در تست واقعی کشف شد (همه در کد لحاظ شده)

۱) **اتصال‌های نیمه‌کاره:** روی همین شبکه بخشی از درخواست‌ها `RemoteDisconnected`/
`SSLError` می‌دهند بدون هیچ کد HTTP — درحالی‌که API سالم است. پس هر درخواست
`FXEMBED_FETCH_TRIES` (پیش‌فرض ۳) تلاش دارد و ماژول هرگز raise نمی‌کند.

۲) **۴۰۴ گذرا:** `@DataAnalyticEPL` یک بار `404` داد و بار بعد `200`؛ `404` در این
API معنایش «کاربر نیست **یا** timeline خالی است». با تلاش مجدد حل می‌شود.

۳) **حساب‌های بدون توییت اصلی:** `@LiverpoolFF` و `@mnstr_mntlt` در timeline
پیش‌فرض `404` می‌دهند ولی پروفایلشان سالم و فعال است. با یک بار
`with_replies=1` (که تایم‌لاین گفتگوها را می‌دهد) خوانده می‌شوند و نتیجه به
**توییت/ریتوییت خودشان** محدود و ریپلای‌های بی‌ارزش حذف می‌شوند.
با این fallback نرخ موفقیت از ۲۵/۲۹ (۸۶٪) به ۲۷/۲۹ (۹۳٪) رسید.

۴) **polling افزایشی:** پارامتر `since` پشتیبانی می‌شود و API با `204 No Content`
می‌گوید «هیچ پست تازه‌تری نیست» (تست واقعی: `since=now+1h → 204`).
`FXEMBED_USE_SINCE=true` تایم‌استمپ آخرین توییت هر حساب را در
`data/twitter_state.json` (کلید `fxembed_since`) نگه می‌دارد و سیکل بعد
`since = آخرین‌زمان − FXEMBED_SINCE_OVERLAP_SECONDS (۹۰۰ ثانیه)` می‌فرستد.
حاشیه‌ی ۱۵ دقیقه‌ای عمدی است: اگر یک آیتم پایین‌دستی شکست بخورد، سیکل بعد
دوباره دیده می‌شود (سیاست «هیچ خبری گم نشود»). با این حاشیه ۲۰۴ عملاً وقتی
می‌آید که حساب واقعاً ساکن است.

## وضعیت fallback ها

- `XSCRAPE_FALLBACK_CLASSIC` **حفظ شد** (پیش‌فرض `true`، رفتار عوض نشد) ولی
  لاگ آن از `log.error` به یک **هشدار صریح** تغییر کرد:
  «falling back to classic/Nitter — but classic/Nitter is no longer a reliable
  source (dead mirrors); the working source is TWITTER_MODE=fxembed».
  دلیل: نیتر مرده است، پس این fallback فقط «ادامه دادن بدون خطا» است؛ ولی
  خرابش نکردیم چون حذفش یک تغییر رفتاری بی‌فایده بود.
- `TWITTER_MODE=classic` حذف/خراب **نشد** — فقط legacy/dead/unreliable مستند شد.
- حالت `fxembed` عمداً **هیچ fallback ی به نیتر ندارد** (افتادن به منبع مرده فقط
  سیکل را هدر می‌دهد)؛ به‌جایش در صورت خالی‌بودن همه‌ی حساب‌ها شمارنده‌ی سلامت
  `fxembed_dead_cycle` ثبت و لاگ خطا داده می‌شود.

## بازبینی production (۲۰۲۶-۰۹-۲۷) — پنج نکته‌ی بازبینی و پاسخ عملی

۱) **pagination واقعی در polling (مهم‌ترین اصلاح).** نسخه‌ی اول فقط یک صفحه
می‌خواند؛ اگر در پنجره‌ی `since` بیش از `count=20` پست جمع شده بود (مثلاً بعد از
یک downtime طولانی) بقیه بی‌صدا گم می‌شد. حالا `_own_statuses_paged()` با
`cursor.bottom` تا تهیه‌شدن نتیجه یا سقف `FXEMBED_MAX_PAGES` (پیش‌فرض ۳ ⇒ سقف سخت
۶۰ توییت در هر حساب) جلو می‌رود، id های تکراری را حذف می‌کند و اگر `cursor` جلو
نرود یا صفحه خالی شود می‌ایستد (سقف «تعداد درخواست» تضمین می‌کند حلقه هرگز
بی‌نهایت نشود). صفحه‌های بعدی فقط `cursor` می‌گیرند چون طبق مستندات `since` فقط
بدون cursor معتبر است. بدون `since` عمداً یک صفحه کافی است (polling عادی تازه‌ترین‌ها
را می‌خواهد).

۲) **`sleep` بی‌فایده حذف شد.** throttle واقعی فقط `FXEMBED_WORKERS` است؛ تست
`test_fxembed_never_sleeps_between_accounts` هر sleep را در مسیر fetch خطا می‌دهد.
کامنت سقف نرخ هم اصلاح شد: **API v2 = ۱۰۰۰ درخواست در دقیقه به‌ازای هر IP** (نه
«سقف محدودکننده ندارد»).

۳) **تست partial failure اضافه شد:** state فقط برای حساب‌های موفق به‌روز می‌شود،
حساب ناموفق سیکل بعد **بدون** `since` و کاملاً تازه خوانده می‌شود، و شکست جزئی
باعث `fxembed_dead_cycle` (که فقط برای «همه‌ی حساب‌ها خالی» است) نمی‌شود؛ خبرهای
موفق هم در همان سیکل وارد پایپ‌لاین می‌شوند.

۴) **cooldown برای حساب‌های ساسپند/حذف‌شده.** تابع `fxembed.suspension_reason()`
وقتی (و فقط وقتی) یک حساب چیزی نداد، پروفایلش را می‌پرسد و
`suspended` / `not_found` را تشخیص می‌دهد. نتیجه در
`data/twitter_state.json → fxembed_cooldown` با مهلت
`FXEMBED_SUSPENDED_COOLDOWN` (پیش‌فرض ۲۴ ساعت) ذخیره می‌شود و تا آن موقع هیچ
درخواستی برای آن حساب نمی‌رود؛ بعد از پایان مهلت دوباره بررسی می‌شود (شاید
حساب برگشته باشد).

۵) **تست دو سیکل واقعی (`scripts/manual_tests/test_fxembed_cycles.py`)** — همان چیزی
که بازبینی خواسته بود ثابت شود:

```text
سیکل ۱ (بدون since):  2 حساب · 36 توییت · 10.7s
سیکل ۲ (since = آخرین زمان − 900s):  2 حساب · 115 توییت · 16.3s
  → توییت‌های سیکل ۱ که در سیکل ۲ نبودند: 0     (چیزی گم نشد)
  → توییت‌های تکراری: 36                        (حاشیه‌ی ۱۵ دقیقه‌ای عمدی)
  → توییت‌های تازه: 79
@AnfieldSector → بدون نتیجه → suspended  → اجرای بعد skip
@LiverpoolFF   → ۲۰ توییت (with_replies fallback) → سیکل بعد با pagination به ۶۰
```

نکته‌ی مهمی که همین تست روشن کرد: **`since` صفحه را برش نمی‌دهد، فقط یک «سیگنال
poll» است** — اگر هیچ پستی *جدیدتر* از آن لحظه نباشد `204` می‌دهد، وگرنه صفحه‌ی
معمولی را برمی‌گرداند. پس حاشیه‌ی ۹۰۰ ثانیه‌ای دقیقاً همان چیزی است که باعث
می‌شود سیکل بعد دوباره همان توییت‌های تازه را ببیند (و DB تکراری‌ها را حذف کند)،
و pagination تضمین می‌کند در روزهای شلوغ (deadline day) توییت‌های قدیمی‌ترِ
همان پنجره هم از قلم نیفتند.

اعتبارسنجی نهایی بعد از این اصلاحات: `tests/test_fxembed.py` از ۲۸ به **۴۰ تست**
رسید و کل سوییت **۲۴۸ pass** شد؛ اجرای زنده‌ی ۲۹ حساب: **۲۷/۲۹ = ۹۳٫۱٪** با
۵۲۸ توییت (۲۵ حساب مدیادار، ۱۲ ویدیو، ۲۳ نقل‌قول).

## محدودیت‌های باقی‌مانده

- ۲ حساب ساسپند (`@AnfieldSector`, `@Anfieldmedia_`) از هیچ منبعی خبر نمی‌دهند —
  تصمیم مالک: از لیست حذف شوند یا بمانند.
- FxEmbed یک سرویس ثالث است؛ اگر خودش روزی محدود شود، عملاً همان ریسک وابستگی
  ثالث را داریم (ولی بدون کلید/هزینه و با OpenAPI رسمی). راه‌حل بلندمدت:
  self-host کردن FxEmbed (`docs.fxembed.com` → Self-Hosting) یا GraphQL داخلی X.
- متن توییت‌های بلند (note_tweet) از همان `text` کامل می‌آید؛ پشتیبانی relay
  قدیمی `note_tweet` لازم نیست.
- فیلترها همان‌های قبلی‌اند: `ROMANO_KEYWORDS` همچنان تاریخ‌مصرف دارد و باید قبل از
  هر پنجره‌ی نقل‌وانتقالاتی بازبینی شود.

## فایل‌های تغییرکرده

- `sources/fxembed.py` (جدید) — کلاینت + mapper به قرارداد entry
- `sources/twitter.py` — `_fetch_fxembed`, `_entries_to_items` (استخراج حلقه‌ی
  مشترک از `_fetch_xscrape`)، dispatch در `fetch()`/`item_from_url()`، هشدار fallback
- `config.py` — مجاز شدن `fxembed` + تنظیمات `FXEMBED_*` + کامنت هشدار fallback
- `tests/test_fxembed.py` (جدید) — ۲۸ تست بدون شبکه
- `scripts/manual_tests/test_fxembed.py` (جدید) — تست زنده روی ۲۹ حساب از مسیر بات
- `scripts/diagnostics/probe_sources.py` (جدید) — کاوش خام x.com / FxEmbed
- `scripts/diagnostics/probe_fx_contract.py`, `probe_fx_since.py` (جدید) — قرارداد API
- `.env.example`, `docs/PROJECT_STATUS.md`, `docs/ARCHITECTURE.md` — مستندسازی

## Next

- `.env` این مخزن روی `TWITTER_MODE=fxembed` تنظیم شد (هر دو خط تکراری ۱۱۲ و ۱۳۲
  هم‌مقدار شدند — یکی‌شان را پاک کنید). برگشت به رفتار قبلی: `TWITTER_MODE=xscrape`.
- مالک تصمیم بگیرد ۲ حساب ساسپند (`@AnfieldSector`, `@Anfieldmedia_`) در
  `TWITTER_ACCOUNTS` بمانند یا حذف شوند (الان بی‌صدا در هر سیکل تلاش می‌کنند و
  ~۱۰ ثانیه وقت سیکل می‌گیرند).
- بازبینی `ROMANO_KEYWORDS` قبل از پنجره‌ی نقل‌وانتقالاتی زمستان.
- مانیتور `data/twitter_state.json → fxembed_since` و لاگ `fxembed: N/29 accounts`
  برای دیدن نرخ موفقیت در طول زمان.
- اگر روزی FxEmbed ناپایدار شد: اول self-host (docs.fxembed.com → Self-Hosting)،
  بعد GraphQL داخلی X — مسیر/هدرهای لازم در همین کاوش مستند شده‌اند (GraphQL
  وجودش تأیید شد؛ `scripts/diagnostics/probe_sources.py x` رشته‌های
  `graphql`/`UserByScreenName` را در HTML امروز x.com نشان می‌دهد).

