"""ماژول دانلودر ابری از طریق UserBot و @twittervid_bot.

نحوه کارکرد:
  ۱. ارسال خودکار لینک توییت به @twittervid_bot از طریق کلاینت کاربری (Telethon)
  ۲. دریافت آنی فایل ویدیوی آماده درون سرورهای ابری تلگرام (بدون دانلود روی هارد یا مصرف ترافیک سیستم)
  ۳. فوروارد یا ارسال مستقیم ویدیو به کانال/گروه ادمین با کپشن فارسی
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import threading
import config

import re

log = logging.getLogger("userbot")

try:
    from telethon import TelegramClient, events
    from telethon.errors import AuthKeyDuplicatedError
    _HAS_TELETHON = True
except ImportError:
    _HAS_TELETHON = False
    log.warning("Telethon is not installed: pip install telethon")


def parse_button_quality_and_size(text: str) -> tuple[int, float]:
    """
    متن دکمه را تحلیل می‌کند و (رزولوشن_عددی, حجم_مگابایت) برمی‌گرداند.
    نمونه‌ها:
      '1080p - 86.6 MB' -> (1080, 86.6)
      '720p - 25.3 MB'  -> (720, 25.3)
      '360p - 8.2 MB'   -> (360, 8.2)
      '480p - 1.2 GB'   -> (480, 1200.0)
      '240p - 800 KB'   -> (240, 0.8)
    """
    text = (text or "").strip()
    res_m = re.search(r'(\d{3,4})p?', text, re.I)
    resolution = int(res_m.group(1)) if res_m else 0
    
    size_mb = 0.0
    size_m = re.search(r'([\d\.]+)\s*(GB|MB|KB)', text, re.I)
    if size_m:
        try:
            val = float(size_m.group(1))
            unit = size_m.group(2).upper()
            if unit == 'GB':
                size_mb = val * 1024.0
            elif unit == 'MB':
                size_mb = val
            elif unit == 'KB':
                size_mb = val / 1024.0
        except ValueError:
            size_mb = 0.0
            
    return resolution, size_mb


def select_best_quality_button(buttons, max_mb: float = 48.0):
    """
    انتخاب بهترین کیفیت که حجم آن زیر سقف مجاز (پیش‌فرض ۴۸ مگابایت) باشد.
    اگر همه دکمه‌ها بالای ۴۸ مگابایت بودند، کم‌حجم‌ترین دکمه انتخاب می‌شود.
    """
    all_btns = []
    for row in buttons:
        for btn in row:
            txt = getattr(btn, "text", "") or ""
            res, sz = parse_button_quality_and_size(txt)
            all_btns.append((res, sz, btn, txt))
            
    if not all_btns:
        return None
        
    under_limit = [b for b in all_btns if b[1] == 0.0 or b[1] <= max_mb]
    if under_limit:
        # مرتب‌سازی: بالاترین رزولوشن اول، سپس بالاترین حجم زیر سقف
        under_limit.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return under_limit[0][2]
        
    # اگر همگی بالای سقف حجم بودند، کم‌حجم‌ترین را انتخاب کن
    all_btns.sort(key=lambda x: x[1] if x[1] > 0 else 999999.0)
    return all_btns[0][2]


class TwitterVidDownloader:
    def __init__(self):
        self.api_id = getattr(config, "USERBOT_API_ID", None)
        self.api_hash = getattr(config, "USERBOT_API_HASH", None)
        self.session_name = getattr(config, "USERBOT_SESSION", "lfc_userbot")
        self.bot_target = getattr(config, "USERBOT_BOT_TARGET", "@twittervid_bot")
        self.client: Optional[TelegramClient] = None
        self._dead = False   # سشن باطل شده (AuthKeyDuplicated) — دیگر تلاش نکن
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    def is_configured(self) -> bool:
        """آیا API_ID و API_HASH در .env تنظیم شده‌اند؟"""
        return bool(_HAS_TELETHON and self.api_id and self.api_hash)

    def _start_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def _ensure_loop(self):
        if self._thread is None or not self._thread.is_alive():
            self._ready.clear()
            self._thread = threading.Thread(target=self._start_loop, daemon=True, name="UserBotLoop")
            self._thread.start()
            self._ready.wait(timeout=5)

    def download_and_forward_sync(
        self,
        tweet_url: str,
        target_chat_id: int | str,
        caption: str = "",
        timeout_seconds: int = 40,
    ) -> bool:
        """اجرای سنکرون و ایمن در هر ترد پایتون بدون خطای Event Loop."""
        if self._dead:
            log.debug("UserBot session is dead (AuthKeyDuplicated) — skipping. "
                      "Re-login with userbot_login.py after deleting the session file.")
            return False
        if not self.is_configured():
            return False
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self.download_and_forward(tweet_url, target_chat_id, caption, timeout_seconds),
            self._loop,
        )
        try:
            return future.result(timeout=timeout_seconds + 5)
        except Exception as e:
            log.error("download_and_forward_sync error: %s", e)
            return False

    async def _get_client(self) -> TelegramClient:
        if self.client and self.client.is_connected():
            return self.client
        
        proxy = None
        if config.PROXY:
            try:
                from urllib.parse import urlparse
                p = urlparse(config.PROXY)
                import socks
                ptype = socks.SOCKS5 if "socks5" in p.scheme else socks.HTTP
                proxy = (ptype, p.hostname, p.port)
            except Exception as e:
                log.debug("userbot proxy parse failed: %s", e)

        self.client = TelegramClient(
            self.session_name,
            int(self.api_id),
            str(self.api_hash),
            proxy=proxy,
        )
        await self.client.connect()
        try:
            await self.client.get_dialogs(limit=50)
        except Exception:
            pass
        return self.client

    async def download_and_forward(
        self,
        tweet_url: str,
        target_chat_id: int | str,
        caption: str = "",
        timeout_seconds: int = 40,
    ) -> bool:
        """ارسال لینک به @twittervid_bot، دریافت ویدیو در کلود و ارسال مستقیم به چت مقصد."""
        if not self.is_configured():
            log.warning("UserBot is not configured in .env (USERBOT_API_ID, USERBOT_API_HASH)")
            return False

        try:
            client = await self._get_client()
            if not await client.is_user_authorized():
                log.error("UserBot session is not authorized. Please run py -3.12 userbot_login.py first.")
                return False

            bot = await client.get_input_entity(self.bot_target)
            
            # تبدیل آیدی مقصد به انتیتی معتبر
            try:
                cid = int(str(target_chat_id).strip())
                target = await client.get_entity(cid)
            except Exception:
                target = await client.get_input_entity(target_chat_id)

            log.info("Sending tweet url to %s: %s", self.bot_target, tweet_url)
            await client.send_message(bot, tweet_url)

            # گوش دادن به پیام‌ها و کلیک روی دکمه کیفیت
            loop = asyncio.get_running_loop()
            future_reply = loop.create_future()

            async def process_msg(msg):
                if not msg:
                    return
                # ۱. اگر ویدیو آماده بود:
                if msg.video or (msg.document and any(
                    getattr(attr, "__class__", None) and attr.__class__.__name__ == "DocumentAttributeVideo"
                    for attr in (getattr(msg.document, "attributes", None) or [])
                )):
                    if not future_reply.done():
                        future_reply.set_result(msg)
                    return

                # ۲. اگر دکمه‌های انتخاب کیفیت آمد، بهترین کیفیت زیر ۵۰ مگابایت را خودکار انتخاب کن:
                if msg.buttons:
                    chosen_btn = select_best_quality_button(msg.buttons, max_mb=48.0)
                    if chosen_btn:
                        log.info("Auto-clicking best quality under 50MB on %s: '%s'", self.bot_target, getattr(chosen_btn, "text", ""))
                        try:
                            await chosen_btn.click()
                        except Exception as e:
                            log.debug("click button error: %s", e)

            @client.on(events.NewMessage(chats=bot))
            async def new_msg_handler(event):
                await process_msg(event.message)

            @client.on(events.MessageEdited(chats=bot))
            async def edit_msg_handler(event):
                await process_msg(event.message)

            try:
                video_message = await asyncio.wait_for(future_reply, timeout=timeout_seconds)
                client.remove_event_handler(new_msg_handler)
                client.remove_event_handler(edit_msg_handler)

                log.info("Received cloud video from %s — sending to %s...", self.bot_target, target_chat_id)
                await client.send_file(
                    target,
                    video_message.media,
                    caption=caption if caption else None,
                    parse_mode="html" if caption else None,
                )
                return True
            except asyncio.TimeoutError:
                client.remove_event_handler(new_msg_handler)
                client.remove_event_handler(edit_msg_handler)
                log.warning("Timeout waiting for %s reply (%ds)", self.bot_target, timeout_seconds)
                return False

        except AuthKeyDuplicatedError:
            log.critical(
                "UserBot session is DEAD (AuthKeyDuplicatedError): the session file was "
                "used from two different IPs at the same time. Fix: 1) stop any other "
                "bot/instance using this session, 2) delete the session file "
                "(%s.session), 3) re-login: python userbot_login.py",
                self.session_name,
            )
            self._dead = True
            try:
                if self.client:
                    await self.client.disconnect()
            except Exception:
                pass
            self.client = None
            return False
        except Exception as e:
            log.error("UserBot download failed: %s", e)
            return False


_downloader_instance: Optional[TwitterVidDownloader] = None


def get_downloader() -> TwitterVidDownloader:
    global _downloader_instance
    if _downloader_instance is None:
        _downloader_instance = TwitterVidDownloader()
    return _downloader_instance
