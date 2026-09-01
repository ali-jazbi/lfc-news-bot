"""LFC News Bot — حلقه اصلی.

حالت پیش‌فرض = manual:
  ربات فقط در گروه تست/ادمین پیش‌نمایش می‌گذارد. با دکمه
  "\U0001F4E4 نسخه آماده انتشار" یک پیام تمیز (بدون دکمه و لینک منبع) در همان
  گروه می‌فرستد تا ادمین خودش فوروارد/کپی کند.
  با دکمه "\U0001F4E5 ارسال به کانال" مستقیم روی کانال عمومی منتشر می‌شود.

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
import re
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import channel_guard
import config
import db
import formatter
import health
import media
import sample_item
import source_health
import translate
from concurrent.futures import ThreadPoolExecutor, as_completed
from ai.tracing import news_id_of, trace
from sources import lfc_official, romano, twitter, outlet_rss, bluesky
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
def _sources():
    """لیست (source_id, label, fn) — با احترام به ENABLE_* فعلی."""
    out = []
    if config.ENABLE_LFC:
        out.append(("lfc_official", "سایت باشگاه", lfc_official.fetch))
    if getattr(config, "ENABLE_OUTLET_RSS", True):
        out.append(("outlet_rss", "خبرگزاری رسمی", outlet_rss.fetch))
    if getattr(config, "ENABLE_BLUESKY", False):
        out.append(("bluesky", "بلواسکای", bluesky.fetch))
    if getattr(config, "ENABLE_TWITTER", True):
        out.append(("twitter", "توییتر", twitter.fetch))
    elif config.ENABLE_ROMANO:
        out.append(("romano", "رومانو", romano.fetch))
    return out


def _fetch_source(source_id, label, fn):
    """یک منبع را می‌خواند؛ سلامت و backoff (مرحله ۹) را اعمال می‌کند.
    هیچ‌وقت exception به بیرون نمی‌دهد — یک منبع خراب کل چرخه را نمی‌شکند."""
    if not source_health.is_due(source_id):
        log.debug("source %s in backoff — skipped this cycle", source_id)
        return []
    t0 = time.time()
    try:
        got = fn(limit=config.MAX_ITEMS_PER_CYCLE)
        ms = (time.time() - t0) * 1000
        health.record_ok(label, ms=ms, kind="source")
        source_health.mark_ok(source_id, items=len(got or []), latency_ms=ms)
        return got or []
    except Exception as e:
        health.record_fail(label, e, kind="source")
        source_health.mark_fail(source_id, error=str(e))
        log.error("source error %s: %s", label, e)
        return []


def collect():
    """همه منابع به‌صورت هم‌زمان خوانده می‌شوند (timeout isolation):
    یک منبع کند دیگر منبع‌های سالم را block نمی‌کند (مرحله ۱۰)."""
    sources = _sources()
    if not sources:
        return []
    results = {}
    with ThreadPoolExecutor(max_workers=min(len(sources), 5)) as pool:
        futures = {
            pool.submit(_fetch_source, sid, label, fn): sid
            for sid, label, fn in sources
        }
        for fut in as_completed(futures):
            sid = futures[fut]
            try:
                results[sid] = fut.result()
            except Exception as e:
                log.error("collect worker %s crashed: %s", sid, e)
                results[sid] = []
    items = []
    for sid, _, _ in sources:
        items += results.get(sid) or []
    return items


def _get_editor():
    """سردبیر AI — هر بار ساخته می‌شود تا state سبک بماند."""
    from ai import create_editor
    return create_editor()


_processing_keys = set()
_processing_lock = threading.Lock()


def process_item(item, force=False, reply_to=None):
    """یک خبر را از مسیر کامل عبور می‌دهد و در گروه ادمین/تست می‌گذارد.

    force → فیلتر تکراری خاموش.
    reply_to → اگر ست شود، پیام پیش‌نمایش به آن message_id ریپلای می‌شود
    (برای وقتی ادمین خودش لینک توییت را فرستاده).
    وقتی HERMES_ENABLED=false رفتار قبلی دقیقاً حفظ می‌شود (فقط ترجمه + ارسال).
    """
    if not item:
        return False

    key = db.make_key(item)
    with _processing_lock:
        if key in _processing_keys:
            log.info("Already processing %s — skipping concurrent run", key)
            return False
        if not force and db.is_duplicate(item):
            return False
        _processing_keys.add(key)
        # ثبت فوری با وضعیت processing تا سیکل‌های موازی متوجه شوند
        if not config.HERMES_ENABLED:
            db.save(item, status="processing")

    try:
        return _process_item_internal(item, key, force=force, reply_to=reply_to)
    finally:
        with _processing_lock:
            _processing_keys.discard(key)


def _has_translatable_text(text):
    """آیا متن حداقل یک حرف از هر الفبایی دارد؟

    ایموجی/عدد/لینک حرف نیستند — توییت‌های مدیا‌محض (مثل ⏳️ لیورپول)
    باید بدون ورود به موتور ترجمه مدیریه شوند وگرنه آلارم بی‌دلیل می‌دهند.
    """
    return bool(re.search(r"[^\W\d_]", text or "", re.UNICODE))


def _process_item_internal(item, key, force=False, reply_to=None):
    nid = news_id_of(item)
    notes = []
    editor = None

    # --------------------------------------------------------- مرحله AI
    if config.HERMES_ENABLED:
        db.save(item, status=db.STATUS_ANALYZING)
        try:
            editor = _get_editor()
            analysis = editor.analyze(item)
            db.record_analysis(key, analysis.to_dict())
            if analysis.decision == "reject":
                db.mark_attempt(key, db.STATUS_REJECTED,
                                error="AI: " + (analysis.reason or "rejected"))
                health.record_counter("ai_rejected")
                trace(nid, "DECISION", decision="reject",
                      reason=(analysis.reason or "")[:90])
                log.info("AI rejected (%s): %s", analysis.category,
                         (item.get("title") or "")[:70])
                return False
            if editor.needs_verification(analysis, item):
                db.mark_attempt(key, db.STATUS_VERIFICATION)
                try:
                    vr = editor.verify(item, analysis)
                    if vr and vr.verified:
                        notes.append(
                            "\u2705 راستی‌آزمایی شد ({:.0%} با {} شواهد)".format(
                                vr.confidence, len(vr.evidence)))
                    elif vr:
                        notes.append(
                            "\U0001F50D شواهد مستقل کافی نیست — لطفاً بازبینی کن")
                        health.record_counter("verification_human")
                except Exception as e:
                    log.warning("verification failed: %s", e)
                    notes.append("\U0001F50D راستی‌آزمایی ناقص بود — بازبینی کن")
                db.mark_attempt(key, db.STATUS_APPROVED_BY_AI)
            else:
                db.mark_attempt(key, db.STATUS_APPROVED_BY_AI)
        except Exception as e:
            log.exception("AI stage crashed for %s — continuing legacy path", nid)
            db.mark_attempt(key, db.STATUS_APPROVED_BY_AI, error=str(e)[:200])
            editor = None
    else:
        db.save(item, status="new")

    log.info("translating: %s", (item.get("title") or "")[:70])
    tr = None
    if not _has_translatable_text((item.get("title") or "") + " "
                                  + (item.get("body") or "")):
        # متن قابل ترجمه ندارد (فقط ایموجی/مدیا/لینک).
        if force:
            # لینک ادمین — ادمین خودش انتخاب کرده: متن اصلی passthrough می‌شود
            # تا پست مدیا‌محض به پیش‌نمایش برسد؛ بدون آلارم و بدون مصرف ترجمه.
            log.info("no translatable text — passing through untranslated")
            tr = {"title": item.get("title") or "", "body": item.get("body") or "",
                  "importance": "normal", "tags": [], "provider": "raw"}
        else:
            # آیتم ارگانیک بی‌متن — بی‌سروصدا رد می‌شود.
            log.info("skipped (no translatable text): %s",
                     (item.get("title") or "")[:50])
            db.mark_attempt(key, "skipped", error="no translatable text")
            trace(nid, "TRANSLATION", success=False, reason="no_text")
            return False
    else:
        tr = translate.translate(item)
    if not tr:
        if force:
            # لینک ادمین: ترجمه شکست خورد ولی آیتم (معمولاً مدیا) نباید گم شود —
            # پیش‌نویس با متن اصلی + نوت هشدار ساخته می‌شود؛ ادمین خودش تصمیم می‌گیرد.
            log.warning("translation failed on admin link — passing through untranslated")
            notes.append("\u26A0\uFE0F \u062A\u0631\u062C\u0645\u0647 \u0646\u0627\u0645\u0648\u0641\u0642 \u0628\u0648\u062F \u2014 \u0645\u062A\u0646 \u0627\u0635\u0644\u06CC \u06AF\u0630\u0627\u0634\u062A\u0647 \u0634\u062F")
            tr = {"title": item.get("title") or "", "body": item.get("body") or "",
                  "importance": "normal", "tags": [], "provider": "raw"}
        else:
            db.mark_attempt(key, "skipped", error="translation chain failed")
            trace(nid, "TRANSLATION", success=False)
            return False

    # QC ترجمه (مرحله ۶) — فقط وقتی HERMES روشن است
    if config.HERMES_ENABLED and editor is not None:
        from ai.quality_control import translate_with_qc
        try:
            tr, review, human_review = translate_with_qc(item, editor, tr=tr)
            if human_review:
                notes.append(
                    "\U0001FA7A ترجمه کیفیت پایینی دارد — قبل از انتشار اصلاح کن")
        except Exception as e:
            log.warning("translation QC failed: %s", e)

    # نگهبان کانال: خبر را نمی‌بلاکد، فقط به ادمین هشدار می‌دهد
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
        log.info("channel dupe warning (%d%%): %s", score, (tr.get("title") or "")[:50])
        log.debug("similar post in channel: %s", sample)
        health.record_counter("channel_dupe")

    # اگر منبع دیگری هم همین خبر را داده، جلویش را نمی‌گیریم
    # فقط به ادمین خبر می‌دهیم که تأیید دوم هم دارد
    try:
        others = db.similar_sources(item)
    except Exception:
        others = []
    if others:
        notes.append("\U0001F501 این خبر را این‌ها هم داده‌اند: " + "، ".join(others[:4]))
        log.info("shared with: %s", ", ".join(others[:4]))

    item["translated"] = tr
    if config.HERMES_ENABLED:
        db.update_payload(key, item)
    else:
        db.save(item, status="new")
    caption = formatter.build_admin_caption(item, tr)
    if notes:
        caption += "\n" + "\n".join(notes)

    if DRY_RUN:
        print("\n" + "=" * 60)
        print("IMAGE:", item.get("image"))
        print("IMAGES:", item.get("images"))
        print("VIDEO:", item.get("video_url"))
        print("VIDEO_THUMB:", item.get("video_thumb"))
        print(caption)
        original = formatter.build_original_message(item)
        if original:
            print("-" * 60)
            print(original)
        print("=" * 60 + "\n")
        db.set_status(key, "sent_admin")
        return True

    high = tr.get("importance") == "high"
    images = [u for u in (item.get("images") or []) if u]
    video = item.get("video_url")
    thumb = item.get("video_thumb")
    video_urls = [u for u in (item.get("video_urls") or []) if u]
    video_local = None
    thumb_local = None

    # عکس خودکار: HERMES روشن → انتخاب هوشمند (مرحله ۷)؛ خاموش → رفتار قدیمی
    if config.HERMES_ENABLED and editor is not None:
        if not images and not item.get("image") and not video:
            from ai.image_selector import select_image
            try:
                chosen, _ = select_image(item, editor)
                if chosen:
                    item["image"] = chosen
                    images = [chosen]
            except Exception as e:
                log.warning("image selection failed: %s", e)


    # خط لوله ویدیو ابری یا لوکال
    video_sent_by_userbot = False
    if video and config.ENABLE_USERBOT_VIDEOS and not DRY_RUN:
        try:
            import userbot_downloader
            ub = userbot_downloader.get_downloader()
            if ub.is_configured():
                tweet_url = item.get("url") or video
                log.info("Requesting cloud video from @twittervid_bot for: %s", tweet_url)
                video_sent_by_userbot = ub.download_and_forward_sync(
                    tweet_url=tweet_url,
                    target_chat_id=config.ADMIN_CHAT_ID,
                    caption="",
                )
                if video_sent_by_userbot:
                    log.info("Cloud video delivered via UserBot successfully!")
                    msg = tg.send_message(
                        config.ADMIN_CHAT_ID,
                        caption,
                        reply_markup=formatter.keyboard(key, config.PUBLISH_MODE),
                        silent=not high,
                        reply_to=reply_to,
                    )
                    if msg:
                        status = db.STATUS_PENDING_ADMIN if config.HERMES_ENABLED else "sent_admin"
                        db.set_admin_msg(key, msg.get("message_id"), status=status)
                    return True
        except Exception as e:
            log.warning("UserBot cloud download failed, falling back to local: %s", e)

    # خط لوله ویدیو محلی (در صورت عدم استفاده از یوزربات)
    if video and not video_sent_by_userbot and not DRY_RUN:
        try:
            mp = media.process(video, thumb)
            if mp["ok"]:
                video_local = mp["video_path"]
                thumb_local = mp["thumb_path"]
                trace(nid, "VIDEO", state="ready",
                      duration=round(mp.get("duration") or 0, 1))
            else:
                trace(nid, "VIDEO", state=mp.get("state"),
                      error=(mp.get("error") or "")[:90])
                if mp.get("retry"):
                    notes.append("\U0001F3AC ویدیو با URL مستقیم امتحان می‌شود: "
                                 + (mp.get("error") or "")[:60])
                    caption = formatter.build_admin_caption(item, tr)
                    if notes:
                        caption += "\n" + "\n".join(notes)
                else:
                    notes.append("\U0001F3AC ویدیو نامعتبر بود: "
                                 + (mp.get("error") or "")[:60])
                    video = None
                    caption = formatter.build_admin_caption(item, tr)
                    if notes:
                        caption += "\n" + "\n".join(notes)
        except Exception as e:
            log.warning("video pipeline failed: %s", e)

    if video and not video_sent_by_userbot and not DRY_RUN:
        # چند ویدیو → آلبوم ویدیویی با یک کپشن مشترک روی مورد اول
        to_send = video_urls if len(video_urls) >= 2 else ([video] if video else [])
        if len(to_send) >= 2:
            res = tg.send_media_group(config.ADMIN_CHAT_ID, to_send,
                                     caption=caption,
                                     silent=not high,
                                     media_type="video")
            if res:
                msg = tg.send_message(
                    config.ADMIN_CHAT_ID,
                    "\u200b",
                    reply_markup=formatter.keyboard(key, config.PUBLISH_MODE),
                    silent=not high,
                    reply_to=reply_to,
                )
            else:
                log.warning("video album failed (%s) — falling back to individual videos", tg.last_error)
                for vurl in to_send:
                    tg.send_video(config.ADMIN_CHAT_ID, vurl, silent=not high,
                                  thumb=thumb_local or thumb, reply_to=reply_to)
                msg = tg.send_message(
                    config.ADMIN_CHAT_ID,
                    caption,
                    reply_markup=formatter.keyboard(key, config.PUBLISH_MODE),
                    silent=not high,
                    reply_to=reply_to,
                )
        else:
            if video_local:
                try:
                    with open(video_local, "rb") as fh:
                        tg.upload_video(config.ADMIN_CHAT_ID, fh.read(),
                                        silent=not high,
                                        filename=os.path.basename(video_local),
                                        reply_to=reply_to)
                except Exception as e:
                    log.error("local video upload failed: %s", e)
                finally:
                    media.cleanup(video_local)
                    media.cleanup(thumb_local)
                    video_local = None
                    thumb_local = None
            else:
                tg.send_video(config.ADMIN_CHAT_ID, video, caption=caption, silent=not high,
                              thumb=thumb_local or thumb, reply_to=reply_to)
            msg = tg.send_message(
                config.ADMIN_CHAT_ID,
                "\u200b",
                reply_markup=formatter.keyboard(key, config.PUBLISH_MODE),
                silent=not high,
                reply_to=reply_to,
            )
    elif len(images) >= 2:
        # دکمه روی آلبوم کار نمی‌کند — اول آلبوم را جدا می‌فرستیم،
        # بعد کپشن + دکمه‌ها را به صورت پیام متنی جداگانه
        tg.send_media_group(config.ADMIN_CHAT_ID, images, silent=not high)
        msg = tg.send_message(
            config.ADMIN_CHAT_ID,
            caption,
            reply_markup=formatter.keyboard(key, config.PUBLISH_MODE),
            silent=not high,
            reply_to=reply_to,
        )
    else:
        msg = tg.send_post(
            config.ADMIN_CHAT_ID,
            caption,
            image=item.get("image"),
            video=video_local or video,
            thumb=thumb_local or thumb,
            reply_markup=formatter.keyboard(key, config.PUBLISH_MODE),
            silent=not high,
            reply_to=reply_to,
        )
    if msg:
        status = db.STATUS_PENDING_ADMIN if config.HERMES_ENABLED else "sent_admin"
        db.set_admin_msg(key, msg.get("message_id"), status=status)
        trace(nid, "TELEGRAM", upload="success")

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
                log.warning("original text not sent (%s) \u2014 retrying without blockquote",
                            getattr(tg, "last_error", "?"))
                tg.send_message(
                    config.ADMIN_CHAT_ID,
                    formatter.build_original_message(item, expandable=False),
                    silent=True,
                    reply_to=msg.get("message_id"),
                )

        log.info("\u2192 posted to group: %s", (item.get("title") or "")[:70])
        return True

    # شکست ارسال → هیچ‌وقت گم‌شدن ساکت: retry_pending با خطا و شمارنده تلاش
    err = getattr(tg, "last_error", "") or "send failed"
    db.mark_attempt(key, db.STATUS_RETRY_PENDING, error=err, retry=True)
    trace(nid, "TELEGRAM", upload="failed", retry_pending=True, error=err[:80])
    health.record_counter("send_failed")
    log.error("sending to group failed (check ADMIN_CHAT_ID): %s", err)
    return False


def _send_final_post(target, text, item):
    """ارسال نسخه نهایی (کانال یا نسخه آماده گروه).

    برای چند ویدیو، آلبوم ویدیویی با یک کپشن مشترک روی مورد اول ارسال می‌شود؛
    برای تک‌ویدیو، رفتار قبلی حفظ می‌شود.
    """
    video = item.get("video_url")
    video_urls = [u for u in (item.get("video_urls") or []) if u]

    if video and getattr(config, "ENABLE_USERBOT_VIDEOS", False):
        try:
            import userbot_downloader
            ub = userbot_downloader.get_downloader()
            if ub.is_configured():
                tweet_url = item.get("url") or video
                log.info("Final video via UserBot for: %s", tweet_url)
                if ub.download_and_forward_sync(
                    tweet_url=tweet_url,
                    target_chat_id=target,
                    caption=text,
                ):
                    return True
        except Exception as e:
            log.warning("UserBot final video failed, falling back to bot: %s", e)

    if len(video_urls) >= 2:
        res = tg.send_media_group(target, video_urls, caption=text, media_type="video")
        if res:
            return res
        log.warning("final media-group failed (%s) — falling back to single video", tg.last_error)
        video = video_urls[0]

    return tg.send_post(target, text,
                        image=item.get("image"),
                        images=item.get("images"),
                        video=video,
                        thumb=item.get("video_thumb"))


def send_to_channel(key):
    """نسخه آماده انتشار را مستقیم روی کانال عمومی می‌فرستد.
    ادمین با این دکمه تصمیم می‌گیرد خبر مستقیم منتشر شود."""
    row = db.get(key)
    if not row:
        return False, "این خبر در دیتابیس نیست"
    item = row["payload"]
    tr = item.get("translated")
    if not tr:
        return False, "ترجمه ذخیره نشده"

    target = config.channel_target()
    if not target:
        return False, "CHANNEL_ID یا CHANNEL_USERNAME در .env تنظیم نیست"

    text = formatter.build_caption(item, tr)
    images = item.get("images")

    # حلقه بازخورد انسانی: تصمیم AI در برابر اقدام واقعی ادمین
    try:
        analysis = db.get_analysis(key)
        db.record_feedback(
            key,
            ai_decision=(analysis or {}).get("decision") if analysis else None,
            human_action="send_to_channel",
            reason="",
        )
    except Exception as e:
        log.debug("feedback record failed: %s", e)

    res = _send_final_post(target, text, item)
    if res:
        db.set_status(key, "published")
        return True, "\u2705 روی کانال منتشر شد"
    return False, "خطا در انتشار روی کانال"


def approve(key, chat_id):
    """اگر PUBLISH_MODE == auto باشد مستقیم روی کانال منتشر می‌کند؛
    اگر manual باشد نسخه تمیز را در گروه ادمین می‌گذارد."""
    row = db.get(key)
    if not row:
        return False, "این خبر در دیتابیس نیست"
    item = row["payload"]
    tr = item.get("translated")
    if not tr:
        return False, "ترجمه ذخیره نشده"

    text = formatter.build_caption(item, tr)
    images = item.get("images")

    # حلقه بازخورد انسانی (مرحله ۱۲): تصمیم AI در برابر اقدام واقعی ادمین
    try:
        analysis = db.get_analysis(key)
        db.record_feedback(
            key,
            ai_decision=(analysis or {}).get("decision") if analysis else None,
            human_action="approve",
            reason="",
        )
    except Exception as e:
        log.debug("feedback record failed: %s", e)

    res = _send_final_post(chat_id, text, item)
    if res:
        db.set_status(key, "approved")
        return True, "\U0001F4E4 نسخه آماده ارسال شد"
    return False, "خطا در ارسال نسخه نهایی"


# ------------------------------------------------------------------ poller
_last_prune = [0.0]


def maybe_prune():
    """هر PRUNE_INTERVAL یک‌بار دیتابیس را پاک‌سازی می‌کند تا حافظه اشتراکی
    پر نشود. فقط ردیف‌های قدیمی/فشرده می‌شوند — ردیف تازهٔ لازم برای دکمه‌ها
    دست نمی‌خورد."""
    interval = int(os.environ.get("DB_PRUNE_INTERVAL_SECONDS", "3600"))
    if interval <= 0:
        return
    now = time.time()
    if now - _last_prune[0] < interval:
        return
    _last_prune[0] = now
    try:
        try:
            import db_prune
        except ImportError:
            from scripts.maintenance import db_prune
        s = db_prune.prune(dry=False)
        log.info("db prune: %d deleted, %d trimmed", s["deleted"], s["trimmed"])
    except Exception as e:
        log.warning("db prune failed: %s", e)

    # سوئپ رسانه: هر فایل ویدیویی عجیب‌مانده (crash وسط کار) پاک می‌شود
    try:
        media.sweep_old(max_age_hours=int(
            os.environ.get("MEDIA_MAX_AGE_HOURS", "24")))
    except Exception as e:
        log.warning("media sweep failed: %s", e)


def retry_pending_sends(limit=5):
    """خبرهایی که ارسال‌شان قبلاً شکست خورده دوباره امتحان می‌شوند — هیچ خبری
    به‌خاطر یک خطای موقت تلگرام گم نمی‌شود (مرحله ۸/۱۱). بعد از سقف تلاش → failed
    با خطای ذخیره‌شده (نه حذف)."""
    retried = 0
    for row in db.retryable_items(limit=limit):
        key = row["key"]
        item = row["payload"]
        tr = item.get("translated")
        if not tr:
            db.mark_attempt(key, db.STATUS_FAILED, error="no translation payload")
            continue
        nid = news_id_of(item)
        trace(nid, "TELEGRAM", step="retry", attempt=(row.get("retry_count") or 0) + 1)
        caption = formatter.build_admin_caption(item, tr)
        try:
            msg = tg.send_post(
                config.ADMIN_CHAT_ID, caption,
                image=item.get("image"),
                images=[u for u in (item.get("images") or []) if u],
                video=item.get("video_url"),
                thumb=item.get("video_thumb"),
                reply_markup=formatter.keyboard(key, config.PUBLISH_MODE),
            )
        except Exception as e:
            msg = None
            tg.last_error = str(e)
        if msg:
            db.set_admin_msg(key, msg.get("message_id"),
                             status=db.STATUS_PENDING_ADMIN)
            trace(nid, "TELEGRAM", retry="success")
            retried += 1
        else:
            db.mark_attempt(key, db.STATUS_RETRY_PENDING,
                            error=getattr(tg, "last_error", "retry failed"), retry=True)
            trace(nid, "TELEGRAM", retry="failed")
    if retried:
        log.info("retried %d pending send(s)", retried)
    return retried


def run_cycle(force=False):
    health.record_counter("cycles")
    maybe_prune()
    # اول تلاش‌های ناتمام قبلی، بعد خبرها
    retry_pending_sends()
    items = collect()
    log.info("collected %d items", len(items))
    if not items:
        log.warning("no items from sources. test with: python main.py --sample")
        return 0
    sent = 0
    for it in items:
        if sent >= config.MAX_ITEMS_PER_CYCLE:
            break
        if process_item(it, force=force):
            sent += 1
            time.sleep(2)
    log.info("sent %d item(s) this cycle", sent)
    return sent


def drain_pending_updates(timeout=5):
    """آپدیت‌های در انتظار (کلیک دکمه‌ها/دستورات) را یک‌بار می‌گیرد و پردازش می‌کند.

    برای اجراهای کوتاه‌مدت و بدون حلقه‌ی دائمی (مثلاً یک اجرای زمان‌بندی‌شده
    در GitHub Actions) لازم است، وگرنه کلیک روی دکمه‌های «انتشار/رد/ترجمه
    مجدد» هیچ‌وقت پردازش نمی‌شود.
    """
    offset = None
    try:
        updates = tg.get_updates(offset=offset, timeout=timeout)
    except Exception as e:
        log.warning("failed to fetch pending updates: %s", e)
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
            log.warning("failed to fetch pending updates: %s", e)
            break
        if updates is None:
            break  # خطای تلگرام — همان‌جا رها کن؛ سیکل بعدی دوباره امتحان می‌شود


def poller_loop():
    first_run = db.count() == 0
    while not _stop.is_set():
        started = time.time()
        try:
            if first_run and config.BOOTSTRAP_SILENT:
                items = collect()
                for it in items:
                    db.save(it, status="skipped")
                log.info("first run: %d old items recorded silently", len(items))
                first_run = False
            else:
                run_cycle()
        except Exception as e:
            log.exception("poller error: %s", e)

        wait = max(5, config.POLL_INTERVAL - (time.time() - started))
        _stop.wait(wait)


# ------------------------------------------------------------------ bot
def _is_admin(user_id):
    """اگر ADMIN_USER_IDS خالی باشد همه اجازه دارند (رفتار قدیم)،
    وگرنه فقط آیدی‌های فهرست شده اجازه دارند."""
    if not config.ADMIN_USER_IDS:
        return True
    return user_id in config.ADMIN_USER_IDS


def handle_callback(cq):
    data = cq.get("data", "")
    cid = cq["id"]
    msg = cq.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    msg_id = msg.get("message_id")
    from_user = cq.get("from", {})
    user = from_user.get("first_name", "admin")

    if not _is_admin(from_user.get("id")):
        tg.answer_callback(cid, "\u26d4 اجازه نداری این دکمه را بزنی.", alert=True)
        log.warning(
            "\u062aلاش دکمه از کاربر غیرمجاز: %s (%s)",
            from_user.get("id"), user,
        )
        return

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
            label = f"\u2705 نسخه آماده توسط {user} ارسال شد"
            tg.edit_markup(
                chat_id, msg_id, {"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]}
            )
    elif action == "s2c":
        ok, message = send_to_channel(key)
        tg.answer_callback(cid, message, alert=not ok)
        if ok:
            label = f"\u2705 ارسال شد به کانال توسط {user}"
            tg.edit_markup(
                chat_id, msg_id, {"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]}
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


# فقط لینک توییت (با یا بدون https / www / mobile / query مثل ?s=46 از اپ موبایل)
_TWEET_LINK_ONLY = re.compile(
    r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/\w{1,15}/status(?:es)?/\d+/?"
    r"(?:\?\S*)?$",
    re.I,
)


def _handle_tweet_link(url, chat_id, reply_to=None):
    """لینک خام توییت را مثل یک خبر عادی پردازش می‌کند — همان پیش‌نمایش و ۳ دکمه.
    reply_to → پیش‌نمایش به همان پیامِ لینک ریپلای می‌شود."""
    from sources import twitter as twitter_src

    item = twitter_src.item_from_url(url)
    if not item:
        tg.send_message(chat_id, "⚠️ استخراج توییت ناموفق بود — حذف شده یا x.com بلاک کرد. دوباره امتحان کن.")
        return

    if process_item(item, force=True, reply_to=reply_to):
        log.info("tweet link processed: %s", url)
    else:
        tg.send_message(chat_id, "⚠️ پردازش توییت ناتمام ماند — لاگ را ببین.")


def handle_message(m):
    text = (m.get("text") or "").strip()
    chat_id = m.get("chat", {}).get("id")
    from_user = m.get("from", {})

    # لینک خام توییت → استخراج کامل مثل بقیه خبرها (ادمین خودش انتخابش کرده،
    # پس فیلترهای سن/طول/کلیدواژه اینجا معنا ندارند)
    if _TWEET_LINK_ONLY.match(text) and _is_admin(from_user.get("id")):
        tg.send_message(chat_id, "\U0001F50E در حال استخراج توییت...", silent=True,
                        reply_to=m.get("message_id"))
        threading.Thread(target=_handle_tweet_link, args=(text, chat_id, m.get("message_id")),
                         daemon=True).start()
        return

    if not text.startswith("/"):
        return
    cmd = text.split()[0].split("@")[0]

    # /id همیشه باز می‌ماند تا خودت بتونی آیدیات را بگیری و توی ADMIN_USER_IDS بگذاری
    if cmd != "/id" and not _is_admin(from_user.get("id")):
        tg.send_message(chat_id, "\u26d4 اجازه نداری این دستور را بزنی.")
        log.warning(
            "\u062aلاش دستور از کاربر غیرمجاز: %s (%s)",
            from_user.get("id"), from_user.get("first_name"),
        )
        return

    if cmd == "/id":
        tg.send_message(chat_id, f"chat_id این گفتگو: <code>{chat_id}</code>\nآیدی عددی تو: <code>{from_user.get('id')}</code>")
    elif cmd == "/status":
        tg.send_message(
            chat_id,
            "\u2705 ربات فعال است\n"
            f"حالت انتشار: <b>{'دستی' if config.PUBLISH_MODE == 'manual' else 'خودکار'}</b>\n"
            f"خبرهای ثبت‌شده: {db.count()}\n"
            f"بازه چک منابع: هر {config.POLL_INTERVAL} ثانیه",
        )
    elif cmd == "/health":
        try:
            src_report = source_health.report()
        except Exception:
            src_report = ""
        tg.send_message(
            chat_id,
            health.report(translate.chain_names()) + "\n\n"
            + channel_guard.status()
            + (("\n\n" + src_report) if src_report else ""),
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
        tg.send_message(chat_id, "در حال چ�� کردن منابع...")

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
            "/errors — آخرین خطاهای ثبت‌شده\n\n"
            "دکمه‌های خبر:\n"
            "\U0001F4E4 نسخه آماده انتشار — نسخه تمیز در همین گروه\n"
            "\U0001F4E5 ارسال به کانال — مستقیم روی کانال عمومی\n"
            "\U0001F504 ترجمه مجدد — بازبینی ترجمه",
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
            updates = tg.get_updates(offset=offset, timeout=30)
        except Exception as e:
            log.exception("bot loop error: %s", e)
            updates = None
        if updates is None:
            # get_updates شکست خورد (قطعی تلگرام/شبکه) — بلافاصله دوباره نزنیم؛
            # وگرنه حلقه‌ی پرتعداد ۵۰۲ می‌سازد (دیشب ۱۱ درخواست در ۰.۱۳ ثانیه!)
            time.sleep(10)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            if "callback_query" in u:
                handle_callback(u["callback_query"])
            elif "message" in u:
                handle_message(u["message"])


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
            log.error("BOT_TOKEN is empty - set it in .env.")
            sys.exit(1)
        if not config.ADMIN_CHAT_ID:
            log.error("ADMIN_CHAT_ID is empty — run /id in the test group and set it in .env.")
            sys.exit(1)
        me = tg.get_me()
        if not me:
            log.error("could not connect to Telegram (check token or proxy).")
            sys.exit(1)
        log.info("connected to @%s | publish mode: %s", me.get("username"), config.PUBLISH_MODE)

        # از این به بعد هشدارهای health در گروه ادمین می‌افتند
        health.set_notifier(
            lambda text: tg.send_message(config.ADMIN_CHAT_ID, text, silent=False)
        )

    if args.sample:
        for it in sample_item.all_samples():
            process_item(it, force=True)
            time.sleep(1)
        log.info("sample items sent. keep the bot running with python main.py to test buttons.")
        return

    if args.once or args.test:
        if not DRY_RUN:
            log.info("checking pending clicks/commands before new cycle...")
            drain_pending_updates()
        run_cycle(force=args.test)
        log.info("cycle finished and bot closed - buttons only work while the bot is running: python main.py")
        return

    threading.Thread(target=poller_loop, daemon=True).start()
    log.info("service active - checking sources every %d seconds", config.POLL_INTERVAL)
    try:
        bot_loop()
    except KeyboardInterrupt:
        _stop.set()
        log.info("shutdown.")


if __name__ == "__main__":
    main()
