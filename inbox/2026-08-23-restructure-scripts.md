---
type: Decision
date: 2026-08-23
engine: claude-code
status: accepted
tags: [restructure, scripts, layout]
---

# Decision — انتقال اسکریپت‌های کمکی به `scripts/`

## زمینه

ریشهٔ ریپو پر از اسکریپت‌های عیب‌یابی/تست دستی/بنچمارک بود (۲۰+ فایل) که خوانایی کدبیس را خراب می‌کردند. شرط مالک: عملکرد بات نباید دست بخورد.

## تصمیم

اسکریپت‌های غیرهسته در ۴ زیرپوشهٔ `scripts/` قرار گرفتند:

- `scripts/diagnostics/` — check_*، debug_*، doctor، get_chat_id، list_models
- `scripts/manual_tests/` — test_album*، test_send، test_twitter_sources، quick_test
- `scripts/benchmarks/` — benchmark.py
- `scripts/maintenance/` — db_prune.py، evaluate.py

**عمداً جابه‌جا نشدند** (وابسته به runtime): `main.py`، `config.py`، `db.py`، `translate.py`، `media.py`، `formatter.py`، `health.py`، `channel_guard.py`، `source_health.py`، `telegram_api.py`، `sample_item.py` (import مستقیم توسط main)، `ai/`، `sources/`، `install_hermes.py` و `lfc_mcp_server.py` (مسیر MCP در رجیستری Hermes ثبت شده).

هر اسکریپت منتقل‌شده یک path bootstrap سه‌خطی در ابتدای فایل دارد تا از مسیر جدید اجرا شود. مسیرهای `__file__`-محور در `evaluate.py` (golden/results) و `test_send.py` (assets) اصلاح شد. ارجاع‌های docs (QUICKSTART، RELEASE_POLICY، HERMES_INTEGRATION، EVALUATION_REPORT) به‌روز شد. فایل سرگردان `gitignore` (بدون نقطه) حذف شد.

## اعتبارسنجی

- `py_compile` روی همهٔ ماژول‌ها و اسکریپت‌ها: OK
- pytest: **۱۲۳ پاس** — فقط ۲ شکستِ ازقبل‌موجود (`test_e2e_happy_path`، `test_admin_approval_still_required_when_ai_confident`) که روی tree تمیز هم fail می‌شوند
- smoke test: `db_prune.py` (DRY)، `evaluate.py` (گزارش کامل تولید کرد)، `list_models.py`، `check_feeds.py` — همه از مسیر جدید سالم

## Next

- اگر روزی `lfc_mcp_server.py` جابه‌جا شود، باید بعدش `python install_hermes.py --mcp-only` اجرا شود.
