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
                log.warning("fetch_image: response is not an image (%s)", ctype)
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
            log.info("Telegram could not fetch the image itself — manual download and upload...")
            blob = self.fetch_image(photo)
            if blob:
                return self.upload_photo(chat_id, blob, caption, reply_markup, silent)
        return None

    def fetch_video(self, video_url):
        """دانلود ویدیو فقط وقتی تلگرام نتواند URL را مستقیم بگیرد."""
        try:
            r = self.s.get(
                video_url,
                headers={"User-Agent": getattr(config, "USER_AGENT", "Mozilla/5.0")},
                timeout=120, stream=True,
            )
            ctype = r.headers.get("Content-Type", "")
            if r.status_code == 200 and "video" in ctype:
                return r.content
            log.warning("fetch_video %s → HTTP %s (%s)", video_url[:70], r.status_code, ctype)
            self.last_error = "دانلود ویدیو: HTTP " + str(r.status_code)
        except Exception as e:
            log.warning("fetch_video error: %s", e)
            self.last_error = str(e)
        return None

    def upload_video(self, chat_id, video_bytes, caption=None, reply_markup=None,
                     silent=False, filename="video.mp4"):
        """آپلود مستقیم ویدیو — وقتی خود تلگرام نتواند URL را بگیرد."""
        url = API_BASE + self.token + "/sendVideo"
        data = {"chat_id": str(chat_id), "parse_mode": "HTML",
                "disable_notification": "true" if silent else "false"}
        if caption:
            data["caption"] = caption
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        try:
            r = self.s.post(url, data=data,
                            files={"video": (filename, video_bytes)}, timeout=300)
            res = r.json()
            if res.get("ok"):
                return res["result"]
            log.error("telegram upload_video failed: %s", res.get("description"))
            self.last_error = res.get("description") or str(res)
        except Exception as e:
            log.warning("telegram upload_video error: %s", e)
            self.last_error = str(e)
        return None

    def send_video(self, chat_id, video_url, caption=None, reply_markup=None,
                   silent=False, thumb=None):
        """اول URL را به تلگرام می‌دهیم (خودش دانلود می‌کند)؛ اگر نشد
        خودمان دانلود و آپلود می‌کنیم. thumb فقط وقتی خودمان آپلود می‌کنیم."""
        res = self.call(
            "sendVideo",
            chat_id=chat_id,
            video=video_url,
            caption=caption,
            parse_mode="HTML",
            disable_notification=silent,
            reply_markup=reply_markup,
        )
        if res:
            return res
        if isinstance(video_url, str) and video_url.startswith("http"):
            log.info("Telegram could not fetch the video itself — manual download and upload...")
            blob = self.fetch_video(video_url)
            if blob:
                return self.upload_video(chat_id, blob, caption, reply_markup, silent)
        return None

    def send_media_group(self, chat_id, image_urls, caption=None, silent=False):
        """چند عکس را یکجا به صورت آلبوم می‌فرستد (2 تا 10 عکس).

        کپشن فقط روی عکس اول می‌نشیند (محدودیت خود تلگرام). دکمه شیشه‌ای
        روی آلبوم پشتیبانی نمی‌شود — اگر لازم است دکمه‌ها را جدا بفرست.
        اگر کمتر از 2 عکس باشد، خودش را کم می‌کند و با همان تعداد ادامه می‌دهد.
        """
        urls = [u for u in (image_urls or []) if u][:10]
        if len(urls) < 2:
            return None

        media = []
        for i, u in enumerate(urls):
            entry = {"type": "photo", "media": u}
            if i == 0 and caption:
                entry["caption"] = caption
                entry["parse_mode"] = "HTML"
            media.append(entry)

        res = self.call(
            "sendMediaGroup",
            chat_id=chat_id,
            media=media,
            disable_notification=silent,
        )
        if res:
            return res

        log.info("sendMediaGroup with URL failed (%s) — manual download and upload of images...", self.last_error)
        files = {}
        media2 = []
        for i, u in enumerate(urls):
            blob = self.fetch_image(u)
            if not blob:
                continue
            key = f"photo{i}"
            files[key] = (f"photo{i}.jpg", blob)
            entry = {"type": "photo", "media": f"attach://{key}"}
            if i == 0 and caption:
                entry["caption"] = caption
                entry["parse_mode"] = "HTML"
            media2.append(entry)
        if len(media2) < 2:
            return None
        url = API_BASE + self.token + "/sendMediaGroup"
        data = {"chat_id": str(chat_id), "media": json.dumps(media2),
                "disable_notification": "true" if silent else "false"}
        try:
            r = self.s.post(url, data=data, files=files, timeout=120)
            resj = r.json()
            if resj.get("ok"):
                return resj["result"]
            log.error("sendMediaGroup (manual upload) also failed: %s", resj.get("description"))
            self.last_error = resj.get("description") or str(resj)
        except Exception as e:
            log.warning("sendMediaGroup manual upload error: %s", e)
            self.last_error = str(e)
        return None

    def send_post(self, chat_id, text, image=None, images=None, video=None, thumb=None,
                  reply_markup=None, silent=False):
        """اگر ویدیو بود sendVideo می‌فرستد؛ اگر ≤۲ عکس داشت و دکمه‌ای در کار
        نبود آلبوم؛ ورنه طبق رفتار قدیمی: یک عکس + متن (یا فقط متن)."""
        imgs = [u for u in (images or []) if u]

        if video and len(text) <= 1024:
            res = self.send_video(chat_id, video, text, reply_markup, silent, thumb)
            if res:
                return res
            log.warning("video send failed (%s) — continuing with poster/photo", self.last_error)
            if thumb:
                image = thumb
            elif not image and imgs:
                image = imgs[0]

        if len(imgs) >= 2 and not reply_markup:
            caption = text if len(text) <= 1024 else None
            res = self.send_media_group(chat_id, imgs, caption=caption, silent=silent)
            if res:
                if caption is None:
                    self.send_message(chat_id, text, silent=silent)
                return res
            log.warning("album failed (%s) — continuing with a single photo", self.last_error)

        if not image and imgs:
            image = imgs[0]

        if image and len(text) <= 1024:
            res = self.send_photo(chat_id, image, text, reply_markup, silent)
            if res:
                return res
            log.warning("send with photo failed (%s) — text only will be sent", self.last_error)
        elif image:
            if not self.send_photo(chat_id, image, "", None, silent):
                log.warning("separate photo send failed (%s)", self.last_error)
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
