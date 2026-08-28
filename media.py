"""خط لوله رسانه/ویدیو (مرحله ۸) — کاملاً deterministic، در Python.

ویدیو هرگز به Hermes واگذار نمی‌شود. این ماژول:
  1. دانلود به دیسک (stream، با timeout و سقف حجم)
  2. بررسی MIME type
  3. validate با ffprobe (duration/size/codec)
  4. تبدیل با FFmpeg در صورت نیاز (h264/aac/mp4 — سازگار با تلگرام)
  5. ساخت thumbnail
  6. خروجی Telegram-compatible

قانون: شکست = خطای مشخص + وضعیت retry — هیچ‌وقت گم‌شدن ساکت.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time

import requests

import config

log = logging.getLogger("media")

MAX_VIDEO_MB = 48        # سقف تلگرام برای bot ≈ 50MB — با حاشیه امن
DOWNLOAD_TIMEOUT = 120
MIN_DURATION = 0.5       # ویدیوی کمتر از نیم ثانیه = خراب
MAX_DURATION = 600       # بیشتر از ۱۰ دقیقه = مشکوک


class MediaError(Exception):
    pass


def _ffmpeg():
    return shutil.which("ffmpeg")


def _ffprobe():
    return shutil.which("ffprobe")


def _ensure_dir(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


def _download(url: str, dest: str, max_mb=MAX_VIDEO_MB) -> str:
    """دانلود stream به دیسک — اگر از سقف حجم رد شد MediaError."""
    _ensure_dir(dest)
    headers = {"User-Agent": getattr(config, "USER_AGENT", "Mozilla/5.0")}
    r = requests.get(url, headers=headers, timeout=DOWNLOAD_TIMEOUT, stream=True)
    if r.status_code != 200:
        raise MediaError(f"download HTTP {r.status_code}")
    ctype = (r.headers.get("Content-Type") or "").lower()
    if ctype and "video" not in ctype and "octet-stream" not in ctype \
            and "mp4" not in ctype and "webm" not in ctype:
        raise MediaError(f"not a video (Content-Type: {ctype})")
    size = 0
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(1024 * 256):
            f.write(chunk)
            size += len(chunk)
            if size > max_mb * 1024 * 1024:
                raise MediaError(f"video too large ({size // (1024*1024)}MB)")
    os.replace(tmp, dest)
    return dest


def _probe(path: str) -> dict:
    """فراخوانی ffprobe — خروجی dict یا MediaError."""
    fp = _ffprobe()
    if not fp:
        raise MediaError("ffprobe not installed")
    try:
        out = subprocess.run(
            [fp, "-v", "error", "-show_entries",
             "format=duration,size,format_name:stream=codec_type,codec_name",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30,
        )
        import json
        data = json.loads(out.stdout or "{}")
    except Exception as e:
        raise MediaError(f"ffprobe failed: {e}")
    fmt = data.get("format") or {}
    try:
        duration = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    streams = data.get("streams") or []
    vcodec = next((s.get("codec_name") for s in streams
                   if s.get("codec_type") == "video"), "")
    acodec = next((s.get("codec_name") for s in streams
                   if s.get("codec_type") == "audio"), "")
    return {"duration": duration, "size": fmt.get("size"), "vcodec": vcodec,
            "acodec": acodec}


def _transcode(path: str, out_path: str) -> str:
    """تبدیل به mp4/h264/aac — سازگار با تلگرام."""
    ff = _ffmpeg()
    if not ff:
        raise MediaError("ffmpeg not installed")
    _ensure_dir(out_path)
    cmd = [ff, "-y", "-i", path, "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags",
           "+faststart", "-pix_fmt", "yuv420p", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise MediaError(f"ffmpeg failed: {(r.stderr or '')[-300:]}")
    return out_path


def _thumbnail(path: str, out_path: str) -> str:
    """یک فریم میانی به‌عنوان thumbnail (جایی که ویدیو واقعاً شروع شده)."""
    ff = _ffmpeg()
    if not ff:
        return ""
    _ensure_dir(out_path)
    cmd = [ff, "-y", "-i", path, "-ss", "1", "-frames:v", "1", "-vf",
           "scale='min(640,iw)':-2", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not os.path.isfile(out_path):
        return ""
    return out_path


def process(video_url: str, thumb_url=None, out_dir=None) -> dict:
    """خط لوله کامل — خروجی dict (هرگز exception بیرون نمی‌دهد):

    {ok, video_path?, thumb_path?, error?, retry: bool, state: str}
    state: ready | video_upload_failed | invalid | too_large | ...
    """
    out_dir = out_dir or config.MEDIA_DIR
    result = {"ok": False, "error": "", "retry": False, "state": "failed",
              "video_path": None, "thumb_path": None}

    try:
        # ۱) دانلود
        base = "video_" + str(abs(hash(video_url)) % 10 ** 8)
        raw = os.path.join(out_dir, base + ".dl")
        log.info("downloading video: %s", video_url[:80])
        try:
            _download(video_url, raw)
        except MediaError as e:
            result.update(error=str(e), retry=True,
                          state="video_upload_failed")
            return result

        # ۲) validate
        info = _probe(raw)
        dur = info.get("duration") or 0
        if dur < MIN_DURATION:
            cleanup(raw)
            result.update(error="video too short / corrupt",
                          state="invalid")
            return result
        if dur > MAX_DURATION:
            cleanup(raw)
            result.update(error="video too long", state="invalid")
            return result

        # ۳) تبدیل در صورت نیاز
        vcodec = info.get("vcodec") or ""
        acodec = info.get("acodec") or ""
        final = os.path.join(out_dir, base + ".mp4")
        try:
            if vcodec != "h264" or "aac" not in acodec:
                log.info("transcoding (%s/%s) → h264/aac", vcodec, acodec)
                _transcode(raw, final)
            else:
                os.replace(raw, final)
            # فایل خام دیگر لازم نیست — بلافاصله پاک شود (فضای دیسک)
            cleanup(raw)
        except MediaError as e:
            # اگر تب‌دیل نشد، ویدیوی خام را امتحان می‌کنیم (با پرچم)
            cleanup(raw)
            result.update(error=str(e), retry=True,
                          state="video_upload_failed")
            if os.path.isfile(final):
                os.remove(final)
            return result

        # ۴) thumbnail
        thumb_path = None
        try:
            if thumb_url:
                t = os.path.join(out_dir, base + "_t.jpg")
                try:
                    r = requests.get(thumb_url, timeout=30)
                    if r.status_code == 200 and len(r.content) > 1024:
                        with open(t, "wb") as f:
                            f.write(r.content)
                        thumb_path = t
                except Exception:
                    thumb_path = None
            if not thumb_path:
                thumb_path = _thumbnail(final, os.path.join(out_dir, base + "_t.jpg"))
        except Exception as e:
            log.debug("thumbnail failed: %s", e)

        size_mb = os.path.getsize(final) / (1024 * 1024)
        if size_mb > MAX_VIDEO_MB:
            cleanup(final)
            cleanup(thumb_path)
            result.update(error=f"too large after processing ({size_mb:.0f}MB)",
                          state="too_large", retry=False)
            return result

        result.update(ok=True, video_path=final, thumb_path=thumb_path,
                      state="ready", duration=dur)
        return result
    except MediaError as e:
        result.update(error=str(e), state="failed")
        return result
    except Exception as e:
        log.exception("media pipeline crashed: %s", e)
        result.update(error=str(e)[:300], retry=True,
                      state="video_upload_failed")
        return result


def cleanup(path):
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def sweep_old(max_age_hours=24, out_dir=None) -> int:
    """شبکه ایمنی دیسک: هر فایل عجیب‌مانده در پوشه media که از max_age_hours
    قدیمی‌تر است پاک می‌شود (مثلاً اگر پروسه وسط کار crash کرده باشد).
    خروجی: تعداد فایل‌های حذف‌شده."""
    out_dir = out_dir or config.MEDIA_DIR
    removed = 0
    try:
        cutoff = time.time() - max_age_hours * 3600
        for name in os.listdir(out_dir):
            p = os.path.join(out_dir, name)
            try:
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
                    removed += 1
            except Exception:
                pass
    except Exception:
        pass
    if removed:
        log.info("media sweep: removed %d old file(s) from %s", removed, out_dir)
    return removed
