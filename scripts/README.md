# scripts/

اسکریپت‌های کمکی — جزء هستهٔ اجرایی بات نیستند و حذف/تغییرشان روی عملکرد بات اثری ندارد.

هر اسکریپت در ابتدای فایل یک path bootstrap دارد، پس از هر مسیری قابل اجراست:

    python scripts/diagnostics/doctor.py

## ساختار

| پوشه | محتوا |
|---|---|
| `diagnostics/` | عیب‌یابی و تست دستی زیرساخت: `doctor.py` (سرویس‌های ترجمه)، `check_feeds.py` (فیدها)، `check_channel.py` (نگهبان کانال)، `check_accounts.py`، `check_images*.py`، `debug_*.py`، `get_chat_id.py`، `list_models.py` |
| `manual_tests/` | تست‌های دستی ارسال/دریافت: `test_send.py`، `test_album*.py`، `test_twitter_sources.py`، `quick_test.py` |
| `benchmarks/` | مقایسهٔ کیفیت ترجمه: `benchmark.py` → خروجی در `benchmark.md` (روت) |
| `maintenance/` | نگهداری: `db_prune.py` (پاک‌سازی DB)، `evaluate.py` (ارزیابی سردبیر → خروجی در `evaluation/results/`) |

## نکته‌ها

- `sample_item.py` **اینجا نیست** — در روت است چون `main.py` در runtime آن را import می‌کند (`--sample` / `--test`).
- خروجی‌های تولیدشده (benchmark.md، evaluation/results/) gitignore هستند.
- `install_hermes.py` و `lfc_mcp_server.py` هم در روت می‌مانند؛ مسیر MCP server در رجیستری خارجی Hermes ثبت شده.
