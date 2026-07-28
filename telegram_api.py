"""کلاینت سبک Telegram Bot API (بدون وابستگی به کتابخانه سنگین)."""
import json
import os
import time
import logging
import requests

import config

log = logging.getLogger("telegram")
API_BASE = "https://api.telegram.org/bot"


class Telegram:
    def __init__(self, token=None, proxy=None):
        self.token = token or config.BOT_TOKEN
        self.s = requests.Session()
        proxy = proxy if proxy is not None else config.PROXY
        if proxy:
            self.s.proxies = {"http": proxy, "https": proxy}
        self.last_error = ""

    def call(self, method, **params):
        url = API_BASE + self.token + "/" + method
        timeout = params.pop("_timeout", 60)
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(3):
            try:
                r = self.s.post(url, json=params, timeout=timeout)
                data = r.json()
                if data.get("ok"):
                    return data["result"]
                if data.get("error_code") == 429:
                    wait = data.get("parameters", {}).get("retry_after", 5)
                    log.warning("rate limited, sleeping %ss", wait)
                    time.sleep(wait + 1)
                    continue
                log.error("telegram %s failed: %s — %s", method,
                          data.get("error_code"), data.get("description"))
                self.last_error = data.get("description") or str(data)
                return None
            except Exception as e:
                log.warning("telegram %s error (%s/3): %s", method, attempt + 1, e)
                time.sleep(2 * (attempt + 1))
        return None

    # --- helpers ---
    def send_message(self, chat_id, text, reply_markup=None, disable_preview=True,
                     silent=False, reply_to=None):
        return self.call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=disable_preview,
            disable_notification=silent,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to,
        )

    def upload_photo(self, chat_id, image_bytes, caption, reply_markup=None,
                     silent=False, filename="photo.jpg"):
        """آپلود مستقیم فایل — وقتی خود تلگرام نتواند URL را بگیرد."""
        url = API_BASE + self.token + "/sendPhoto"
        data = {"chat_id": str(chat_id), "parse_mode": "HTML",
                "disable_notification": "true" if silent else "false"}
        if caption:
            data["caption"] = caption
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        try:
            r = self.s.post(url, data=data,
                            files={"photo": (filename, image_bytes)}, timeout=90)
            res = r.json()
            if res.get("ok"):
                return res["result"]
            log.error("telegram upload_photo failed: %s", res.get("description"))
            self.last_error = res.get("description") or str(res)
        except Exception as e:
            log.warning("telegram upload_photo error: %s", e)
            self.last_error = str(e)
        return None

    def fetch_image(self, image_url):
        """خودمان عکس را می‌گیریم (با User-Agent واقعی)."""
        try:
            r = self.s.get(
                image_url,
                headers={"User-Agent": getattr(config, "USER_AGENT", "Mozilla/5.0"),
                         "Accept": "image/*,*/*"},
                timeout=45,
            )
            ctype = r.headers.get("Content-Type", "")
            if r.status_code == 200 and "image" in ctype and len(r.content) > 1024:
                return r.content
            if r.status_code == 200 and "image" not in ctype:
                log.warning("fetch_image: پاسخ عکس نیست (%s)", ctype)
                self.last_error = "آدرس عکس نیست (Content-Type: " + ctype + ")"
                return None
            log.warning("fetch_image %s → HTTP %s (%s bytes)",
                        image_url[:70], r.status_code, len(r.content))
            self.last_error = "دانلود عکس: HTTP " + str(r.status_code)
        except Exception as e:
            log.warning("fetch_image error: %s", e)
            self.last_error = str(e)
        return None

    def send_photo(self, chat_id, photo, caption, reply_markup=None, silent=False):
        """اول URL را به تلگرام می‌دهیم؛ اگر نتوانست بگیرد، خودمان آپلود می‌کنیم.

        اگر photo مسیر یک فایل روی دیسک باشد، مستقیم آپلود می‌شود.
        """
        if isinstance(photo, str) and not photo.startswith("http") and os.path.isfile(photo):
            with open(photo, "rb") as fh:
                return self.upload_photo(chat_id, fh.read(), caption, reply_markup,
                                         silent, os.path.basename(photo))
        res = self.call(
            "sendPhoto",
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            disable_notification=silent,
            reply_markup=reply_markup,
        )
        if res:
            return res
        if isinstance(photo, str) and photo.startswith("http"):
            log.info("تلگرام نتوانست عکس را خودش بگیرد — دانلود و آپلود دستی…")
            blob = self.fetch_image(photo)
            if blob:
                return self.upload_photo(chat_id, blob, caption, reply_markup, silent)
        return None

    def send_post(self, chat_id, text, image=None, reply_markup=None, silent=False):
        """اگر عکس داشت با عکس می‌فرستد؛ کپشن بلندتر از ۱۰۲۴ کاراکتر را جدا می‌کند."""
        if image and len(text) <= 1024:
            res = self.send_photo(chat_id, image, text, reply_markup, silent)
            if res:
                return res
            log.warning("ارسال با عکس نشد (%s) — فقط متن می‌رود", self.last_error)
        elif image:
            if not self.send_photo(chat_id, image, "", None, silent):
                log.warning("ارسال عکس جداگانه نشد (%s)", self.last_error)
        return self.send_message(chat_id, text, reply_markup, silent=silent)

    def edit_caption(self, chat_id, message_id, caption, reply_markup=None):
        return self.call(
            "editMessageCaption",
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    def edit_text(self, chat_id, message_id, text, reply_markup=None):
        return self.call(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )

    def edit_markup(self, chat_id, message_id, reply_markup=None):
        return self.call(
            "editMessageReplyMarkup",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )

    def answer_callback(self, callback_id, text="", alert=False):
        return self.call(
            "answerCallbackQuery", callback_query_id=callback_id, text=text, show_alert=alert
        )

    def get_updates(self, offset=None, timeout=30):
        return self.call(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            allowed_updates=["callback_query", "message"],
            _timeout=timeout + 15,
        ) or []

    def get_me(self):
        return self.call("getMe")
