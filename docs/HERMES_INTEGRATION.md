# Hermes Agent Integration

## نقش هرمس

```
Python = reliable infrastructure   (collector, dedup, media, FFmpeg, Telegram, DB)
Hermes = intelligent decision layer (editor, verifier, translator QC, image QC)
LLMs   = reasoning/translation
MCP    = controlled bridge (Hermes ↔ News DB)
Telegram = delivery
```

Hermes هرگز backend را جایگزین نمی‌کند. `ai/hermes_client.py` تنها نقطه تماس
است؛ اگر هرمس در دسترس نباشد → LLM مستقیم (زنجیره خود پروژه) → در آخر
تحلیل قطعی (deterministic). هیچ‌وقت کرش نمی‌کند.

## Setup (انجام‌شده روی این ماشین)

```
Hermes version        : Hermes Agent v0.18.2 (2026.7.7.2)
Installation method   : از قبل نصب بود (%LOCALAPPDATA%\hermes) — نصب/به‌روزرسانی
                        با install.ps1 رسمی (git install)
Model/provider        : openai-api provider ← qwen3.7-plus (https://qwen.aikit.club/v1)
                        با کلید LLM6 خود پروژه (روی ویندوز: OPENAI_API_KEY/OPENAI_BASE_URL
                        در %LOCALAPPDATA%\hermes\.env)
Enabled tools         : web, browser, vision, terminal, file, code_execution,
                        skills, memory, delegation, todo, cronjob, session_search
Web backend           : ddgs (DuckDuckGo) — نصب با `hermes tools post-setup ddgs`
X Search status       : disabled (نیاز به xAI credentials — طبق انتظار)
Vision status         : toolset فعال؛ استفادهٔ عملی به مدل vision-capable بستگی دارد
MCP status            : lfc-news — 10 ابزار، enabled (stdio)
Skills installed      : lfc-news-editor, lfc-news-verifier, lfc-news-translator,
                        lfc-image-selector, lfc-news-quality-control (همه enabled)
```

### نکته‌های مهم setup که در مستندات کلی دیده نمی‌شود

- **provider = `openai-api`** (نه `custom`/`groq`): در این نسخه، `custom` با
  OPENAI_BASE_URL درست کار نمی‌کرد و `groq` در registry نبود. `openai-api`
  + `OPENAI_BASE_URL` + `OPENAI_API_KEY` در `~/.hermes/.env` مسیر درست است.
- **`/no_think`**: مدل‌های Qwen فکر خود را در `<details>` می‌پیچند — افزودن
  `/no_think` به پرامپت، خروجی تمیز می‌دهد (همان ترفند translate.py).
- **محدودکردن toolset با `-t`**: بار کردن ۴۰+ ابزار، schema بزرگ می‌سازد و
  روی مدل‌های فری rate-limit می‌خورد. برای یک‌فراخوانی‌ها از `-t web` یا کمتر استفاده کنید.
- **دسترسی از ایران**: OpenRouter/Groq/Google در این شبکه 403 می‌دهند؛
  qwen.aikit.club (کلید JWT پروژه) و opencode کار می‌کنند. این وضعیت
  environment است، نه باگ کد.

## تست نصب (مرحله ۲۰ پرامپت)

1. `hermes -z "Reply with exactly: HERMES_OK" --cli --yolo` → `HERMES_OK` ✅
2. web_search در agent: ✅ (با ddgs؛ یک تست با شواهد واقعی درباره ادعای
   نقل‌وانتقال بارکولا انجام شد — اختلاف قیمت ۶۰ میلیون ادعایی در برابر
   ارزش‌گذاری Sky Sports را پیدا کرد)
3. MCP: `hermes mcp add lfc-news --command <python> --args <server> --connect-timeout 20`
   → 10/10 ابزار کشف و enable شد ✅
4. تست واقعی claim (طبقه‌بندی + جستجوی شواهد + confidence + importance +
   JSON ساختاریافته) ✅ — خروجی sample:
   ```json
   {"decision": "false", "confidence": 0.85, "importance": "medium",
    "category": "sports_transfer_rumor", "needs_verification": true,
    "verification_summary": "…Sky Sports reports a significant valuation gap…"}
   ```
   (توجه: `decision: "false"` و `importance: "medium"` دقیقاً مواردی است که
   `ai/schemas.py` با schema validation اصلاح می‌کند → review + importance 5.)

## فایل‌های یکپارچگی

| فایل | نقش |
|---|---|
| `ai/hermes_client.py` | کلاینت: agent CLI → LLM مستقیم → خطای کنترل‌شده |
| `ai/editor.py` | سردبیر: tier بندی، تحلیل، verification |
| `ai/quality_control.py` | QC ترجمه (چک قطعی + بازبینی AI با نمونه کانال) |
| `ai/image_selector.py` | انتخاب عکس (هرگز عکس تصادفی) |
| `ai/schemas.py` | Schema validation همه خروجی‌های AI |
| `lfc_mcp_server.py` | MCP stdio — پل کنترل‌شده به DB |
| `hermes_skills/*` | ۵ skill editorial |
| `install_hermes.py` | نصب skills + ثبت MCP (idempotent) |

## قواعد editorial که Hermes نمی‌تواند override کند

Hermes/LLM سلیقهٔ خبری را تعیین می‌کند، ولی **قواعد قطعی کانال همیشه اول
اجرا می‌شوند** (`ai/editor.py`):

- **Hard rules** (`_hard_rules_analysis`): SKIP_KEYWORDS، INCLUDE_WOMEN، خبر
  قدیمی (سال گذشته در عنوان)، opinion/clickbait → reject قطعی. این‌ها قبل از
  فراخوانی AI اعمال می‌شوند و بعد از آن هم دوباره (safety net) — Hermes
  نمی‌تواند خبر women's team یا گالری را publish کند حتی اگر «مرتبط» بداند.
- **Policy guard** (`_policy_guard`): ادعای مهم از منبع غیررسمی → review +
  verification اجباری: injury/breaking ≥۷، transfer/rumour ≥۸. استثنا:
  انتقال تأییدشده از منبع معتبر. «Manager of the Month» از BBC یا «match
  report» از Guardian پابلیش می‌ماند (category غیرحساس).
- **Source health** در تصمیم: منبع degraded/failed → اعتماد کمتر و در صورت
  نیاز review.

نتیجه روی گلدن‌ست (قبل → بعد): Hermes accuracy 0.766 → **0.979**،
reject_precision 1.0، false_accept_risk 0. (جزییات: docs/EVALUATION_REPORT.md)

## Translation QC — fail-closed

وقتی AI QC در دسترس نیست/کرش می‌کند، `TranslationReview` با
`available=false, ok=false, human_review_required=true` برمی‌گردد — هرگز
«ترجمه خوب است» گفته نمی‌شود. Revision هر دو title و body را مستقل پشتیبانی
می‌کند (`revision_title`/`revision_body`)؛ چرخه اصلاح تا `HERMES_MAX_REVISIONS`
و بعد → human_review.

## Verification — research-based + anti-hallucination

- شواهد با **وزن منبع (Tier)** مرتب و امتیازدهی می‌شوند:
  Tier1=Liverpool FC، Tier2=BBC/Sky/Reuters/Athletic/Guardian، Tier3=متخصص
  لیورپول، Tier4=خبرنگار، Tier5=حساب ناشناس. توییت Tier5 با بیانیه رسمی
  امتیاز مساوی ندارد.
- **هرگز تأیید بدون شواهد**: بدون شواهد Tier1 یا دو شواهد Tier2/3 →
  verified=false. این قانون روی خروجی AI هم اعمال می‌شود (نه فقط fallback).
- **Prompt injection**: پرامپت verification صریحاً می‌گوید همه متن وب/RSS
  untrusted است و دستورات داخل محتوا هرگز اطاعت نمی‌شود. (تست:
  tests/test_verification.py)

## اجرا

```bash
python install_hermes.py          # نصب skills + ثبت MCP (یک‌بار)
HERMES_ENABLED=true python main.py  # بات با مغز سردبیری
python main.py                    # بدون AI — رفتار قبلی دقیقاً

python scripts/maintenance/evaluate.py                # ارزیابی قطعی (هزینه صفر)
python scripts/maintenance/evaluate.py --with-ai      # ارزیابی با Hermes واقعی (cache شده)
python scripts/maintenance/evaluate.py --with-ai --verify  # + اجرای verification
```

## وضعیت فعلی provider (در این محیط)

| Provider | وضعیت | توضیح |
|---|---|---|
| qwen.aikit.club (LLM6) | ✅ کار می‌کند | انتخاب فعلی هرمس |
| opencode (LLM1/2) | ⚠️ 429 موقت | سقف فری tier |
| groq (LLM3/11) | ❌ 403 | بلاک/محرومیت |
| OpenRouter (LLM5/7/8) | ❌ 403 security policy | حساب/منطقه |
| Google Gemini (LLM9/10) | ❌ 403 | بلاک منطقه‌ای گوگل |

خط لوله بات مستقل از این‌هاست: `translate.py` زنجیره خودش را دارد و
`ai` همیشه به deterministic fallback می‌رسد.
