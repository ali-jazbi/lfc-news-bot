"""تست‌های خط لوله ویدیو (مرحله ۸/۱۵) — همه چیز mock می‌شود (بدون شبکه،
بدون ffmpeg واقعی)."""
import json
import os
from unittest import mock

import pytest

import media


class FakeResponse:
    def __init__(self, status=200, content=b"x" * 100, ctype="video/mp4",
                 chunks=None):
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        self._chunks = chunks or [content]
        self.content = content

    def iter_content(self, chunk_size=1024):
        return iter(self._chunks)


def _probe_json(duration=10.0, vcodec="h264", acodec="aac", size="1000"):
    return json.dumps({
        "format": {"duration": str(duration), "size": str(size),
                   "format_name": "mov,mp4"},
        "streams": [
            {"codec_type": "video", "codec_name": vcodec},
            {"codec_type": "audio", "codec_name": acodec},
        ],
    })


class FakeRunResult:
    def __init__(self, rc, stdout, stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


def _patch_deps(monkeypatch, tmp_path, probe=None, transcode_rc=0,
                download_ok=True):
    """mock کردن network + ffprobe/ffmpeg.

    probe_ok: ffprobe جواب درست می‌دهد یا نه
    transcode_rc: خروجی ffmpeg هنگام تبدیل (0=موفق، 1=شکست)
    """
    out_dir = str(tmp_path / "media")
    os.makedirs(out_dir, exist_ok=True)

    def fake_get(url, headers=None, timeout=120, stream=False):
        if not download_ok:
            raise media.MediaError("download HTTP 500")
        return FakeResponse()

    monkeypatch.setattr(media.requests, "get", fake_get)
    monkeypatch.setattr(media, "_ffprobe", lambda: "ffprobe")
    monkeypatch.setattr(media, "_ffmpeg", lambda: "ffmpeg")

    def _run(cmd, capture_output=True, text=True, timeout=30):
        joined = " ".join(str(c) for c in cmd)
        if "-show_entries" in joined:  # ffprobe
            return FakeRunResult(0, _probe_json() if probe is None else probe)
        if "libx264" in joined:  # ffmpeg transcode
            if transcode_rc != 0:
                return FakeRunResult(transcode_rc, "", "encoder failed")
            # خروجی واقعی بنویس تا os.path.isfile درست شود
            out = cmd[cmd.index("-pix_fmt") + 2]
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as f:
                f.write(b"x" * 100)
            return FakeRunResult(0, "")
        if "-frames:v" in joined:  # thumbnail
            out = cmd[-1]
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as f:
                f.write(b"jpg")
            return FakeRunResult(0, "")
        return FakeRunResult(0, "")

    run_mock = mock.Mock(side_effect=_run)
    monkeypatch.setattr(media.subprocess, "run", run_mock)
    return out_dir, run_mock


def test_valid_video(monkeypatch, tmp_path):
    out, _ = _patch_deps(monkeypatch, tmp_path)
    r = media.process("https://cdn/video.mp4", out_dir=out)
    assert r["ok"]
    assert r["state"] == "ready"
    assert r["video_path"] and os.path.isfile(r["video_path"])


def test_invalid_video_short(monkeypatch, tmp_path):
    out, _ = _patch_deps(monkeypatch, tmp_path,
                         probe=_probe_json(duration=0.1))
    r = media.process("https://cdn/video.mp4", out_dir=out)
    assert not r["ok"]
    assert r["state"] == "invalid"


def test_unsupported_codec_transcodes(monkeypatch, tmp_path):
    out, run_mock = _patch_deps(monkeypatch, tmp_path,
                                probe=_probe_json(vcodec="vp9", acodec="opus"))
    r = media.process("https://cdn/video.mp4", out_dir=out)
    assert r["ok"]
    # فراخوانی ffmpeg تبدیل انجام شد
    transcode_calls = [c for c in run_mock.call_args_list
                       if "libx264" in str(c)]
    assert transcode_calls


def test_download_timeout(monkeypatch, tmp_path):
    out, _ = _patch_deps(monkeypatch, tmp_path, download_ok=False)
    r = media.process("https://cdn/video.mp4", out_dir=out)
    assert not r["ok"]
    assert r["retry"] is True
    assert r["state"] == "video_upload_failed"


def test_ffmpeg_failure_returns_retry(monkeypatch, tmp_path):
    out, _ = _patch_deps(monkeypatch, tmp_path,
                         probe=_probe_json(vcodec="vp9", acodec="opus"),
                         transcode_rc=1)
    r = media.process("https://cdn/video.mp4", out_dir=out)
    assert not r["ok"]
    assert r["retry"] is True
    assert r["state"] == "video_upload_failed"


def test_never_raises(monkeypatch, tmp_path):
    """هیچ exceptionی از process بیرون نمی‌آید — حالت مشخص برمی‌گردد."""
    def boom(url, headers=None, timeout=120, stream=False):
        raise RuntimeError("totally unexpected")

    monkeypatch.setattr(media.requests, "get", boom)
    r = media.process("https://cdn/video.mp4",
                      out_dir=str(tmp_path / "m"))
    assert "state" in r
    assert r["ok"] is False


def test_upload_retry_state_machine(tmp_db, patched_main):
    """شکست ارسال ویدیو → retry_pending؛ بعد از سقف → failed (نه گم‌شدن)."""
    import db
    import main
    item = {"source": "X", "source_tag": "X", "url": "https://x/1",
            "title": "Video story", "body": "text",
            "video_url": "https://cdn/v.mp4", "translated": {
                "title": "عنوان", "body": "متن", "importance": "normal"}}
    key = db.save(item, status=db.STATUS_RETRY_PENDING)
    db.mark_attempt(key, db.STATUS_RETRY_PENDING, error="upload failed", retry=True)
    db.mark_attempt(key, db.STATUS_RETRY_PENDING, error="upload failed", retry=True)
    db.mark_attempt(key, db.STATUS_RETRY_PENDING, error="upload failed", retry=True)
    # بعد از ۳ تلاش → دیگر retryable نیست
    rows = db.retryable_items(limit=10, max_retries=3)
    assert key not in [r["key"] for r in rows]
    db.mark_attempt(key, db.STATUS_FAILED, error="upload failed permanently")
    row = db.get(key)
    assert row["status"] == "failed"
    assert "upload failed" in (row.get("error") or "")


def test_retry_pending_sends(monkeypatch, tmp_db, patched_main):
    """retry_pending_sends دوباره ارسال می‌کند و موفق → pending_admin."""
    import db
    import main
    item = {"source": "X", "source_tag": "X", "url": "https://x/1",
            "title": "Story", "body": "text",
            "translated": {"title": "عنوان", "body": "متن", "importance": "normal"}}
    key = db.save(item, status=db.STATUS_RETRY_PENDING)
    db.mark_attempt(key, db.STATUS_RETRY_PENDING, error="first fail", retry=True)
    n = main.retry_pending_sends(limit=5)
    assert n == 1
    row = db.get(key)
    assert row["status"] == db.STATUS_PENDING_ADMIN
    assert row["admin_msg"]
