"""پاک‌سازی دوره‌ای دیتابیس — جلوی رشد بی‌حد حافظه در هاست اشتراکی را می‌گیرد.

چرا لازم است: دیتابیس (data/news.db) بدون محدودیت رشد می‌کند — هر خبرِ
شده برای همیشه با payload کامل (body اصلی + ترجمه + همه تصاویر) ذخیره
می‌شود. روی هاست اشتراکی با دیسک محدود این به مرور فضا را پر می‌کند.

دو کار انجام می‌دهد:
  ۱) حذف کامل ردیف‌های قدیمی‌تر از DB_KEEP_DAYS (پیش‌فرض ۷ روز). فیلتر
     تکراری فقط به تاریخِ ۴۸ ساعت اخیر نیاز دارد (db.py: is_duplicate)،
     پس ردیف‌های قدیمی‌تر از این هیچ ارزشی ندارند.
  ۲) فشرده‌سازی payload ردیف‌های باقی‌مانده: body و translated را برای
     ردیف‌های قدیمی‌تر از DB_TRIM_AFTER_HOURS (پیش‌فرض ۲۴ ساعت) پاک
     می‌کند. همین فیلدها بیش‌ترین حجم را دارند و dedup فقط به title/url
     نیاز دارد.

نکته: در حالت manual ردیف‌های «تأیید نشده» (sent_admin/approved) که هنوز
برای دکمه‌ها لازمند، اگر فشرده شوند دیگر نمی‌توانی روی دکمه «نسخه آماده»
بزنی. پس ردیف‌هایی که status در (sent_admin, approved, published) دارند و
تازه‌اند (< ۴۸ ساعت) فشرده نمی‌شوند. فقط ردیف‌های قدیمی و ردیف‌های
rejected/skipped فشرده می‌شوند.

استفاده: خودکار در main.run_cycle هر N سیکل صدا زده می‌شود؛ دستی هم می‌توانی
بزنی:  python db_prune.py
"""
import json
import os
import sqlite3
import time

import config

# پیش‌فرض‌ها — با متغیرهای .env قابل تغییر
DB_KEEP_DAYS = int(os.environ.get("DB_KEEP_DAYS", "7"))
# بعد از چند ساعت body/translated پاک شود
DB_TRIM_AFTER_HOURS = int(os.environ.get("DB_TRIM_AFTER_HOURS", "24"))
# هر چند ثانیه یک‌بار چک شود (بی‌نهایت = خودکار خاموش)
PRUNE_INTERVAL_SECONDS = int(os.environ.get("DB_PRUNE_INTERVAL_SECONDS", "3600"))

# وضعیت‌هایی که هنوز برای دکمه‌های ادمین لازمند — فشرده نمی‌شوند تا تازه‌اند
_ACTIVE_STATUSES = ("new", "sent_admin", "approved")


def _conn():
    import db
    return db._c()


def _now():
    return time.time()


def prune(keep_days=DB_KEEP_DAYS, trim_hours=DB_TRIM_AFTER_HOURS, dry=False):
    """حذف قدیمی‌ها + فشرده‌سازی. خروجی: dict با آمار."""
    c = _conn()
    now = _now()
    stats = {"deleted": 0, "trimmed": 0, "kept": 0}

    # ۱) حذف ردیف‌های قدیمی
    cutoff = now - keep_days * 86400
    cur = c.execute("SELECT key, payload, status FROM items WHERE created_at < ?", (cutoff,))
    old_rows = cur.fetchall()
    stats["deleted"] = len(old_rows)
    if old_rows and not dry:
        for r in old_rows:
            c.execute("DELETE FROM items WHERE key=?", (r[0],))

    # ۲) فشرده‌سازی payload ردیف‌های باقی‌مانده
    trim_cutoff = now - trim_hours * 3600
    cur = c.execute("SELECT key, payload, status, created_at FROM items")
    for key, payload, status, created_at in cur.fetchall():
        if created_at is None or created_at >= trim_cutoff:
            stats["kept"] += 1
            continue
        # ردیف تازه‌ای که هنوز برای دکمه‌ها لازم است را دست نزن
        if status in _ACTIVE_STATUSES and now - created_at < 48 * 3600:
            stats["kept"] += 1
            continue
        try:
            item = json.loads(payload)
        except Exception:
            stats["kept"] += 1
            continue
        # این فیلدها را حذف کن — dedup فقط به title/url نیاز دارد
        removed = False
        for field in ("body", "translated", "images", "video_url", "video_thumb"):
            if field in item:
                item.pop(field, None)
                removed = True
        if removed and not dry:
            c.execute(
                "UPDATE items SET payload=? WHERE key=?",
                (json.dumps(item, ensure_ascii=False), key),
            )
            stats["trimmed"] += 1
        else:
            stats["kept"] += 1

    if not dry:
        c.commit()
    return stats


def vacuum():
    """فشرده‌سازی واقعی فایل — بعد از حذف تعداد زیادی ردیف."""
    c = _conn()
    c.execute("VACUUM")


if __name__ == "__main__":
    # خروجی قابل خواندن برای اجرای دستی
    dry_run = os.environ.get("DB_PRUNE_DRY", "1") == "1"
    s = prune(dry=dry_run)
    mode = "DRY (تغییری نداد)" if dry_run else "اجرا شد"
    print("prune %s: %d حذف، %d فشرده، %d نگه‌داشته" % (mode, s["deleted"], s["trimmed"], s["kept"]))
    if not dry_run:
        vacuum()
        db_size = os.path.getsize(config.DB_PATH)
        print("حجم دیتابیس بعد از VACUUM: %.0f KB" % (db_size / 1024))
