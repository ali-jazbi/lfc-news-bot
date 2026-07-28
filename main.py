"""LFC News Bot — حلقه اصلی.

حالت پیش‌فرض = manual:
  ربات فقط در گروه تست/ادمین پیش‌نمایش می‌گذارد. با دکمه
  "📤 نسخه آماده انتشار" یک پیام تمیز (بدون دکمه و لینک منبع) در همان
  گروه می‌فرستد تا ادمین خودش فوروارد/کپی کند. هیچ چیزی خودکار
  روی کانال نمی‌رود.

دستورات:
  python main.py --sample        → ۲ خبر نمونه (حتی اگر هیچ خبر تازه‌ای نباشد)
  python main.py --test          → یک سیکل واقعی، فیلتر تکراری خاموش
  python main.py --once          → یک سیکل عادی
  python main.py                 → سرویس دائمی
  پرچم --dry-run را به هرکدام اضافه کنی → چیزی به تلگرام نمی‌رود
"""
import argparse
import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

import channel_guard
import config
import db
import formatter
import health
import sample_item
import translate
from sources import lfc_official, romano, twitter
from telegram_api import Telegram


def _setup_logging():
    """دو خروجی: کنسول (خلاصه) و فایل چرخشی (کامل، با تاریخ)."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    con = logging.StreamHandler()
    con.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-12s | %(message)s", "%H:%M:%S"))
    root.addHandler(con)

    try:
        os.makedirs("logs", exist_ok=True)
        # ۵ فایل ۲ مگابایتی → حداکثر ۱۰ مگابایت، دیسک پر نمی‌شود
        fh = RotatingFileHandler(
            os.path.join("logs", "bot.log"),
            maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)-12s | %(message)s"))
        root.addHandler(fh)

        # خطاها جداگانه هم ثبت می‌شوند تا زیر انبوه لاگ گم نشوند
        eh = RotatingFileHandler(
            os.path.join("logs", "errors.log"),
            maxBytes=1024 * 1024, backupCount=3, encoding="utf-8",
        )
        eh.setLevel(logging.WARNING)
        eh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)-12s | %(message)s"))
        root.addHandler(eh)
    except Exception as e:
        con.handle(logging.LogRecord(
            "main", logging.WARNING, "", 0,
            "نوشتن لاگ روی فایل ممکن نشد: %s", (e,), None))


_setup_logging()
log = logging.getLogger("main")

tg = Telegram()
DRY_RUN = False
_stop = threading.Event()
_check_running = False


# ------------------------------------------------------------------ collect
def _fetch_source(label, fn):
    """یک منبع را می‌خواند و سلامتش را ثبت می‌کند."""
    t0 = time.time()
    try:
        got = fn(limit=config.MAX_ITEMS_PER_CYCLE)
        health.record_ok(label, ms=(time.time() - t0) * 1000, kind="source")
        return got or []
    except Exception as e:
        health.record_fail(label, e, kind="source")
        log.error("خطا در منبع %s: %s", label, e)
        return []


def collect():
    items = []
    if config.ENABLE_LFC:
        items += _fetch_source("سایت باشگاه", lfc_official.fetch)
    if getattr(config, "ENABLE_TWITTER", True):
        items += _fetch_source("توییتر", twitter.fetch)
    elif config.ENABLE_ROMANO:
        items += _fetch_source("رومانو", romano.fetch)
    return items


def process_item(item, force=False):
    """یک خبر را ترجمه و در گروه ادمین/تست می‌گذارد. force → فیلتر تکراری خاموش."""
    if not force and db.is_duplicate(item):
        return False

    log.info("ترجمه: %s", (item.get("title") or "")[:70])
    tr = translate.translate(item)
    if not tr:
        db.save(item, status="skipped")
        return False

    # نگهبان کانال: خبر را نمی‌بلاکد، فقط به ادمین هشدار می‌دهد
    notes = []
    hit = channel_guard.check(tr, item)
    if hit:
        score, sample = hit
        try:
            published_by = db.similar_sources(
                item, hours=168, statuses=("approved", "published"), exclude_self=False
            )
        except Exception:
            published_by = []
        who = (" — منبعش در کانال: " + "، ".join(published_by[:3])) if published_by else ""
        notes.append(
            "\u26A0\uFE0F این خبر قبلاً در کانال منتشر شده (شباهت "
            + str(round(float(score))) + "٪)" + who
        )
        log.info("هشدار کانال (%d%%): %s", score, (tr.get("title") or "")[:50])
        log.debug("پست مشابه در کانال: %s", sample)
        health.record_counter("channel_dupe")

    # اگر منبع دیگری هم همین خبر را داده، جلویش را نمی‌گیریم
    # فقط به ادمین خبر می‌دهیم که تأیید دوم هم دارد
    try:
        others = db.similar_sources(item)
    except Exception:
        others = []
    if others:
        notes.append("\U0001F501 این خبر را این‌ها هم داده‌اند: " + "، ".join(others[:4]))
        log.info("خبر مشترک با %s", ", ".join(others[:4]))

    item["translated"] = tr
    key = db.save(item, status="new")
    caption = formatter.build_admin_caption(item, tr)
    if notes:
        caption += "\n" + "\n".join(notes)

    if DRY_RUN:
        print("\n" + "=" * 60)
        print("IMAGE:", item.get("image"))
        print(caption)
        original = formatter.build_original_message(item)
        if original:
            print("-" * 60)
            print(original)
        print("=" * 60 + "\n")
        db.set_status(key, "sent_admin")
        return True

    high = tr.get("importance") == "high"
    msg = tg.send_post(
        config.ADMIN_CHAT_ID,
        caption,
        image=item.get("image"),
        reply_markup=formatter.keyboard(key, config.PUBLISH_MODE),
        silent=not high,
    )
    if msg:
        db.save(item, status="sent_admin", admin_msg=msg.get("message_id"))

        # متن انگلیسی دست‌نخورده، بی‌صدا و در پاسخ به همان پیش‌نمایش
        original = formatter.build_original_message(item)
        if original:
            sent = tg.send_message(
                config.ADMIN_CHAT_ID,
                original,
                silent=True,
                reply_to=msg.get("message_id"),
            )
            if not sent:
                log.warning("متن اصلی نرفت (%s) — بدون بلاک‌کووت تلاش مجدد",
                            getattr(tg, "last_error", "?"))
                tg.send_message(
                    config.ADMIN_CHAT_ID,
                    formatter.build_original_message(item, expandable=False),
                    silent=True,
                    reply_to=msg.get("message_id"),
                )

        log.info("\u2192 در گروه قرار گرفت: %s", (item.get("title") or "")[:70])
        return True
    log.error("ارسال به گروه ناموفق بود (ADMIN_CHAT_ID را چک کن)")
    return False


def approve(key, chat_id):
    """حالت manual: نسخه تمیز را در همان گروه می‌فرستد (بدون دکمه و لینک)
    حالت auto  : مستقیم روی کانال می‌فرستد."""
    row = db.get(key)
    if not row:
        return False, "این خبر در دیتابیس نیست"
    item = row["payload"]
    tr = item.get("translated")
    if not tr:
        return False, "ترجمه ذخیره نشده"

    text = formatter.build_caption(item, tr)

    if config.PUBLISH_MODE == "auto" and config.CHANNEL_ID:
        res = tg.send_post(config.CHANNEL_ID, text, image=item.get("image"))
        if res:
            db.set_status(key, "published")
            return True, "\u2705 روی کانال منتشر شد"
        return False, "خطا در انتشار روی کانال"

    # حالت دستی
    tg.send_message(chat_id, "\U0001F447 نسخه نهایی — فوروارد/کپی کن در کانال", silent=True)
    res = tg.send_post(chat_id, text, image=item.get("image"))
    if res:
        db.set_status(key, "approved")
        return True, "\U0001F4E4 نسخه آماده ارسال شد"
    return False, "خطا در ارسال نسخه نهایی"


# ------------------------------------------------------------------ poller
def run_cycle(force=False):
    health.record_counter("cycles")
    items = collect()
    log.info("جمع‌آوری شد: %d آیتم", len(items))
    if not items:
        log.warning("هیچ خبری از منابع گرفته نشد. برای تست عملکرد: python main.py --sample")
        return 0
    sent = 0
    for it in items:
        if sent >= config.MAX_ITEMS_PER_CYCLE:
            break
        if process_item(it, force=force):
            sent += 1
            time.sleep(2)
    log.info("در این سیکل %d خبر ارسال شد", sent)
    return sent


def drain_pending_updates(timeout=5):
    """آپدیت‌های در انتظار (کلیک دکمه‌ها/دستورات) را یک‌بار می‌گیرد و پردازش می‌کند.

    برای اجراهای کوتاه‌مدت و بدون حلقه‌ی دائمی (مثلاً یک اجرای زمان‌بندی‌شده
    در GitHub Actions) لازم است، وگرنه کلیک روی دکمه‌های «انتشار/رد/ترجمه
    مجدد» هیچ‌وقت پردازش ��می‌شود.
    """
    offset = None
    try:
        updates = tg.get_updates(offset=offset, timeout=timeout)
    except Exception as e:
        log.warning("دریافت آپدیت‌های در انتظار ناموفق بود: %s", e)
        return
    while updates:
        for u in updates:
            offset = u["update_id"] + 1
            if "callback_query" in u:
                handle_callback(u["callback_query"])
            elif "message" in u:
                handle_message(u["message"])
        try:
            updates = tg.get_updates(offset=offset, timeout=2)
        except Exception as e:
            log.warning("دریافت آپدیت‌های در انتظار ناموفق بود: %s", e)
            break


def poller_loop():
    first_run = db.count() == 0
    while not _stop.is_set():
        started = time.time()
        try:
            if first_run and config.BOOTSTRAP_SILENT:
                items = collect()
                for it in items:
                    db.save(it, status="skipped")
                log.info("اجرای اول: %d خبر قدیمی بی‌صدا ثبت شد (بدون اسپم گروه)", len(items))
                first_run = False
            else:
                run_cycle()
        except Exception as e:
            log.exception("خطای poller: %s", e)

        wait = max(5, config.POLL_INTERVAL - (time.time() - started))
        _stop.wait(wait)


# ------------------------------------------------------------------ bot
def handle_callback(cq):
    data = cq.get("data", "")
    cid = cq["id"]
    msg = cq.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    msg_id = msg.get("message_id")
    user = cq.get("from", {}).get("first_name", "admin")

    if ":" not in data:
        tg.answer_callback(cid)
        return
    action, key = data.split(":", 1)
    row = db.get(key)
    if not row:
        tg.answer_callback(cid, "این خبر دیگر در دیتابیس نیست", alert=True)
        return

    if action == "pub":
        ok, message = approve(key, chat_id)
        tg.answer_callback(cid, message, alert=not ok)
        if ok:
            label = (
                f"\u2705 تایید شد توسط {user}"
                if config.PUBLISH_MODE == "manual"
                else f"\u2705 منتشر شد توسط {user}"
            )
            tg.edit_markup(
                chat_id, msg_id, {"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]}
            )
    elif action == "rej":
        db.set_status(key, "rejected")
        tg.answer_callback(cid, "\u274C رد شد")
        tg.edit_markup(
            chat_id,
            msg_id,
            {"inline_keyboard": [[{"text": f"\u274C رد شد توسط {user}", "callback_data": "noop"}]]},
        )
    elif action == "rtr":
        tg.answer_callback(cid, "در حال ترجمه مجدد...")
        item = row["payload"]
        tr = translate.translate(item)
        if not tr:
            tg.answer_callback(cid, "ترجمه مجدد ناموفق بود", alert=True)
            return
        item["translated"] = tr
        db.save(item, status=row["status"], admin_msg=row["admin_msg"])
        new_caption = formatter.build_admin_caption(item, tr)
        kb = formatter.keyboard(key, config.PUBLISH_MODE)
        if msg.get("photo"):
            tg.edit_caption(chat_id, msg_id, new_caption, kb)
        else:
            tg.edit_text(chat_id, msg_id, new_caption, kb)
    else:
        tg.answer_callback(cid)


def handle_message(m):
    text = (m.get("text") or "").strip()
    chat_id = m.get("chat", {}).get("id")
    if not text.startswith("/"):
        return
    cmd = text.split()[0].split("@")[0]

    if cmd == "/id":
        tg.send_message(chat_id, f"chat_id این گفتگو: <code>{chat_id}</code>")
    elif cmd == "/status":
        tg.send_message(
            chat_id,
            "\u2705 ربات فعال است\n"
            f"حالت انتشار: <b>{'دستی' if config.PUBLISH_MODE == 'manual' else 'خودکار'}</b>\n"
            f"خبرهای ثبت‌شده: {db.count()}\n"
            f"بازه چک منابع: هر {config.POLL_INTERVAL} ثانیه",
        )
    elif cmd == "/health":
        tg.send_message(
            chat_id,
            health.report(translate.chain_names()) + "\n\n" + channel_guard.status(),
        )
    elif cmd == "/errors":
        tg.send_message(chat_id, _tail_errors())
    elif cmd == "/sample":
        tg.send_message(chat_id, "در حال ساخت خبر نمونه...")
        threading.Thread(
            target=lambda: process_item(sample_item.get(0), force=True), daemon=True
        ).start()
    elif cmd == "/check":
        global _check_running
        if _check_running:
            tg.send_message(chat_id, "⏳ یک چک منابع همین الان در حال اجراست — صبر کن تمام شود.")
            return
        tg.send_message(chat_id, "در حال چک کردن منابع...")

        def _run_check():
            global _check_running
            _check_running = True
            try:
                run_cycle(force=False)
            finally:
                _check_running = False

        threading.Thread(target=_run_check, daemon=True).start()
    elif cmd in ("/start", "/help"):
        tg.send_message(
            chat_id,
            "دستورات:\n"
            "/id — نمایش chat_id این گروه\n"
            "/status — وضعیت ربات\n"
            "/sample — ارسال یک خبر نمونه برای تست\n"
            "/check — چک فوری منابع واقعی\n"
            "/health — وضعیت سرویس‌های ترجمه و منابع\n"
            "/errors — آخرین خطاهای ثبت‌شده",
        )


def _tail_errors(n=12):
    """آخرین خطاها را از فایل لاگ می‌خواند."""
    path = os.path.join("logs", "errors.log")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
    except FileNotFoundError:
        return "\u2705 فایل خطا هنوز ساخته نشده — یعنی هنوز خطایی رخ نداده."
    except Exception as e:
        return "خواندن لاگ ممکن نشد: " + str(e)
    if not lines:
        return "\u2705 هیچ خطایی ثبت نشده."
    body = "".join(lines)[-3000:]
    return "\U0001F41E <b>آخرین خطاها</b>\n<pre>" + formatter.esc(body) + "</pre>"


def bot_loop():
    offset = None
    while not _stop.is_set():
        try:
            for u in tg.get_updates(offset=offset, timeout=30):
                offset = u["update_id"] + 1
                if "callback_query" in u:
                    handle_callback(u["callback_query"])
                elif "message" in u:
                    handle_message(u["message"])
        except Exception as e:
            log.exception("خطای حلقه ربات: %s", e)
            time.sleep(5)


# ------------------------------------------------------------------ entry
def main():
    global DRY_RUN
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="یک سیکل و خروج")
    ap.add_argument("--test", action="store_true", help="یک سیکل با فیلتر تکراری خاموش")
    ap.add_argument("--sample", action="store_true", help="ارسال خبرهای نمونه")
    ap.add_argument("--dry-run", action="store_true", help="بدون ارسال به تلگرام")
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    db.init()

    if not DRY_RUN:
        if not config.BOT_TOKEN:
            log.error("BOT_TOKEN خالی است — فایل .env را پر کن.")
            sys.exit(1)
        if not config.ADMIN_CHAT_ID:
            log.error("ADMIN_CHAT_ID خالی است — در گروه تست /id بزن و عدد را در .env بگذار.")
            sys.exit(1)
        me = tg.get_me()
        if not me:
            log.error("اتصال به تلگرام برقرار نشد (توکن یا پراکسی را چک کن).")
            sys.exit(1)
        log.info("متصل شد به @%s | حالت انتشار: %s", me.get("username"), config.PUBLISH_MODE)

        # از این به بعد هشداره��ی health در گروه ادمین می‌افتند
        health.set_notifier(
            lambda text: tg.send_message(config.ADMIN_CHAT_ID, text, silent=False)
        )

    if args.sample:
        for it in sample_item.all_samples():
            process_item(it, force=True)
            time.sleep(1)
        log.info("خبرهای نمونه ارسال شدند. برای تست دکمه‌ها ربات را با python main.py روشن نگه دار.")
        return

    if args.once or args.test:
        if not DRY_RUN:
            log.info("بررسی کلیک‌های در انتظار (دکمه/دستور) قبل از سیکل جدید...")
            drain_pending_updates()
        run_cycle(force=args.test)
        log.info("سیکل تمام شد و ربات بسته شد — دکمه‌ها فقط وقتی کار می‌کنند که "
                 "ربات روشن باشد: python main.py")
        return

    threading.Thread(target=poller_loop, daemon=True).start()
    log.info("سرویس فعال شد — چک منابع هر %d ثانیه", config.POLL_INTERVAL)
    try:
        bot_loop()
    except KeyboardInterrupt:
        _stop.set()
        log.info("خاموش شد.")


if __name__ == "__main__":
    main()
