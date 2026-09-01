"""فیکسچرهای مشترک تست — کاملاً بدون شبکه (همه چیز mock می‌شود)."""
import json
import os
import sys
import time

import pytest

# پروژه root را به sys.path اضافه کن (اجرای pytest از tests/)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# --------------------------------------------------------------- DB ایزوله
@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """DB جدا روی دیسک موقت + reset اتصال جهانی."""
    import db
    import config
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "HERMES_ENABLED", False)
    db._conn = None
    db.init()
    yield db
    try:
        db._conn.close()
    except Exception:
        pass
    db._conn = None


@pytest.fixture()
def news_db(tmp_db):
    return tmp_db


# ------------------------------------------------------------- آیتم نمونه
@pytest.fixture()
def sample_item():
    return {
        "source": "Fabrizio Romano",
        "source_tag": "Fabrizio Romano",
        "url": "https://x.com/FabrizioRomano/status/111",
        "title": "Liverpool are working on Bradley Barcola deal",
        "body": ("To be clear: Liverpool are working on Bradley Barcola deal but "
                 "don't expect anything to be agreed in the next hours. Talks are "
                 "ongoing and will take time. Barcola is keen on the move."),
        "image": None,
        "priority": True,
    }


@pytest.fixture()
def official_item():
    return {
        "source": "LFC Official",
        "source_tag": "Liverpool FC",
        "url": "https://www.liverpoolfc.com/news/statement-123",
        "title": "Liverpool FC confirm new contract for Mohamed Salah",
        "body": ("Liverpool Football Club is delighted to confirm that Mohamed "
                 "Salah has signed a new contract extension. The forward has "
                 "committed his future to the club."),
        "image": None,
    }


@pytest.fixture()
def irrelevant_item():
    return {
        "source": "Twitter",
        "source_tag": "Unknown Account",
        "handle": "@random123",
        "url": "https://x.com/random123/status/999",
        "title": "My weekend trip to Italy was amazing",
        "body": ("Spent the weekend hiking through the Italian countryside, the "
                 "food was incredible and the views were stunning."),
        "image": None,
    }


# ---------------------------------------------------------------- فیک تلگرام
class FakeTelegram:
    """شبیه‌ساز telegram_api.Telegram — همه متدها record می‌شوند."""

    def __init__(self):
        self.calls = []
        self.last_error = ""
        self.fail_send = False
        self.sent_messages = []

    def _maybe_fail(self):
        if self.fail_send:
            self.last_error = "test failure"
            return None
        return {"message_id": len(self.sent_messages) + 1}

    def send_message(self, chat_id, text, reply_markup=None, disable_preview=True,
                     silent=False, reply_to=None):
        self.calls.append(("send_message", chat_id, text, reply_to))
        self.sent_messages.append(text)
        r = self._maybe_fail()
        if r:
            r["text"] = text
        return r

    def send_post(self, chat_id, text, image=None, images=None, video=None,
                  thumb=None, reply_markup=None, silent=False, reply_to=None):
        self.calls.append(("send_post", chat_id, text, video))
        self.sent_messages.append(text)
        r = self._maybe_fail()
        if r:
            r["text"] = text
        return r

    def send_video(self, chat_id, video_url, caption=None, reply_markup=None,
                   silent=False, thumb=None, reply_to=None):
        self.calls.append(("send_video", chat_id, video_url))
        return self._maybe_fail()

    def upload_video(self, chat_id, video_bytes, caption=None, reply_markup=None,
                     silent=False, filename="video.mp4"):
        self.calls.append(("upload_video", chat_id, filename))
        return self._maybe_fail()

    def send_media_group(self, chat_id, image_urls, caption=None, silent=False,
                        media_type="photo"):
        self.calls.append(("send_media_group", chat_id, len(image_urls), media_type, caption))
        return self._maybe_fail()

    def get_updates(self, offset=None, timeout=30):
        return []

    def get_me(self):
        return {"username": "testbot"}

    def answer_callback(self, cid, text="", alert=False):
        self.calls.append(("answer_callback", cid, text))
        return True

    def edit_markup(self, chat_id, msg_id, markup):
        self.calls.append(("edit_markup", chat_id, msg_id))
        return True

    def edit_caption(self, chat_id, msg_id, caption, kb=None):
        self.calls.append(("edit_caption", chat_id, msg_id))
        return True

    def edit_text(self, chat_id, msg_id, text, kb=None):
        self.calls.append(("edit_text", chat_id, msg_id))
        return True


@pytest.fixture()
def fake_tg():
    return FakeTelegram()


@pytest.fixture()
def patched_main(monkeypatch, tmp_db, fake_tg):
    """main را با فیک تلگرام و ترجمه فیک آماده می‌کند (بدون شبکه)."""
    import main
    monkeypatch.setattr(main, "tg", fake_tg)

    def _fake_translate(item):
        return {
            "title": "عنوان فارسی",
            "body": ("متن کامل فارسی درباره لیورپول که برای تست به اندازه کافی "
                     "طولانی است تا از حداقل طول مورد نیاز عبور کند و شامل "
                     "اطلاعات اصلی خبر باشد."),
            "importance": "normal",
            "tags": [],
            "provider": "test",
        }

    monkeypatch.setattr(main.translate, "translate", _fake_translate)
    monkeypatch.setattr(main.channel_guard, "check", lambda tr, item=None: None)
    monkeypatch.setattr(main, "DRY_RUN", False)
    return main


# ----------------------------------------------------------------- فیک هرمس
class FakeHermesClient:
    """شبیه‌ساز HermesClient — تست‌ها رفتار را ست می‌کنند."""

    def __init__(self, analysis=None, verification=None, review=None,
                 image=None, fail=False):
        self.analysis = analysis
        self.verification = verification
        self.review = review
        self.image = image
        self.fail = fail
        self.calls = []

    def analyze(self, item, tier="medium"):
        self.calls.append(("analyze", tier))
        if self.fail:
            raise Exception("AI provider down")
        return self.analysis

    def verify(self, item, claim, evidence):
        self.calls.append(("verify", len(evidence)))
        if self.verification:
            return self.verification
        from ai.schemas import VerificationResult
        return VerificationResult(confidence=0.5, verified=bool(evidence),
                                  evidence=evidence, claim=claim, checked_at=0)

    def review_translation(self, item, tr, examples):
        self.calls.append(("review_translation", len(examples)))
        if self.review:
            return self.review
        from ai.schemas import TranslationReview
        return TranslationReview(ok=True, score=0.95, issues=[])

    def select_image(self, item, candidates):
        self.calls.append(("select_image", len(candidates)))
        if self.image:
            return self.image
        from ai.schemas import ImageSelection
        return ImageSelection(image_url=None, confidence=0.0, reason="none")


@pytest.fixture()
def fake_hermes():
    return FakeHermesClient()
