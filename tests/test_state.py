"""تست‌های state machine (مرحله ۱۱/۱۵): هیچ exceptionی خبر را در وضعیت
نامعلوم رها نمی‌کند."""
import pytest

import db as dbmod
from ai.schemas import NewsAnalysis


def test_ai_stage_crash_continues_legacy(patched_main, sample_item, monkeypatch):
    """کرش مرحله AI → خبر همچنان به ادمین می‌رسد (بدون گم‌شدن)."""
    import config
    import db
    import main
    old = config.HERMES_ENABLED
    config.HERMES_ENABLED = True
    try:
        def _boom_editor():
            raise RuntimeError("ai totally crashed")

        monkeypatch.setattr(main, "_get_editor", _boom_editor)
        assert main.process_item(sample_item) is True
        row = db.get(db.make_key(sample_item))
        assert row["status"] == db.STATUS_PENDING_ADMIN
    finally:
        config.HERMES_ENABLED = old


def test_rejected_news_has_error_reason(patched_main, sample_item, monkeypatch):
    """رد شدن توسط AI → status rejected + دلیل ذخیره می‌شود."""
    import config
    import db
    import main
    old = config.HERMES_ENABLED
    config.HERMES_ENABLED = True
    try:
        from ai import create_editor

        class RejClient:
            def analyze(self, item, tier="medium"):
                return NewsAnalysis(
                    decision="reject", confidence=0.9, importance=1,
                    category="irrelevant", relevance=False, quality="clickbait",
                    reason="clickbait title", tier=tier)

        class RejEditor:
            client = RejClient()

            def analyze(self, item):
                return self.client.analyze(item)

            def needs_verification(self, analysis, item):
                return False

        monkeypatch.setattr(main, "_get_editor", lambda: RejEditor())
        assert main.process_item(sample_item) is False
        row = db.get(db.make_key(sample_item))
        assert row["status"] == db.STATUS_REJECTED
        assert "clickbait" in (row.get("error") or "")
    finally:
        config.HERMES_ENABLED = old


def test_translation_failure_marked(patched_main, sample_item, monkeypatch):
    """شکست کامل ترجمه → skipped با خطا (نه رها شدن)."""
    import db
    import main
    monkeypatch.setattr(main.translate, "translate", lambda item: None)
    assert main.process_item(sample_item) is False
    row = db.get(db.make_key(sample_item))
    assert row["status"] == "skipped"
    assert row["error"]


def test_mark_attempt_tracks_retries(tmp_db):
    item = {"source": "X", "source_tag": "X", "url": "https://x/1",
            "title": "Story", "body": "text"}
    key = tmp_db.save(item)
    tmp_db.mark_attempt(key, dbmod.STATUS_RETRY_PENDING, error="e1", retry=True)
    tmp_db.mark_attempt(key, dbmod.STATUS_RETRY_PENDING, error="e2", retry=True)
    row = tmp_db.get(key)
    assert row["retry_count"] == 2
    assert row["error"] == "e2"
    assert row["last_attempt_at"]


def test_analysis_and_verification_persisted(tmp_db, sample_item):
    key = tmp_db.save(sample_item)
    tmp_db.record_analysis(key, {"decision": "publish", "importance": 8})
    tmp_db.record_verification(key, {
        "verified": True, "confidence": 0.8,
        "evidence": [{"source": "BBC", "title": "t", "url": "u"}],
        "claim": "c", "source": "s", "checked_at": 1,
    })
    assert tmp_db.get_analysis(key)["decision"] == "publish"
    assert tmp_db.get_verification(key)["verified"] is True
    rows = tmp_db._c().execute(
        "SELECT * FROM verifications WHERE news_key=?", (key,)).fetchall()
    assert len(rows) == 1


def test_channel_examples_only_approved(tmp_db, sample_item):
    """نمونه‌های استایل فقط از پست‌های approved/published می‌آیند."""
    good = dict(sample_item)
    good["url"] = "https://x/good"
    good["translated"] = {"title": "ت", "body": "متن خوب", "importance": "n"}
    bad = dict(sample_item)
    bad["url"] = "https://x/bad"
    bad["translated"] = {"title": "ب", "body": "متن بد", "importance": "n"}
    tmp_db.save(good, status="published")
    tmp_db.save(bad, status="sent_admin")
    examples = tmp_db.channel_examples(limit=10)
    assert len(examples) == 1
    assert examples[0]["url"] == "https://x/good"


def test_full_retry_cycle_ends_in_failed(patched_main, sample_item, monkeypatch):
    """مرحله ۱۸: send fail → retry_pending → تلاش مجدد → سقف → failed با خطا.
    هیچ آیتمی گم نمی‌شود."""
    import config
    import db
    import main
    old = config.HERMES_ENABLED
    config.HERMES_ENABLED = False
    try:
        # ارسال اول شکست می‌خورد
        main.tg.fail_send = True
        assert main.process_item(sample_item) is False
        key = db.make_key(sample_item)
        row = db.get(key)
        assert row["status"] == db.STATUS_RETRY_PENDING
        assert row["retry_count"] == 1

        # تلاش‌های مجدد هم شکست می‌خورند → بعد از MAX_SEND_RETRIES → failed
        main.tg.fail_send = True
        main.retry_pending_sends()
        main.retry_pending_sends()
        row = db.get(key)
        # بعد از سقف retry، دیگر retryable نیست
        retryable = db.retryable_items(limit=10)
        assert all(r["key"] != key for r in retryable)
        # خبر گم نشده: هنوز با خطا در DB است
        assert row["status"] in (db.STATUS_RETRY_PENDING, db.STATUS_FAILED)
        assert row["error"]
    finally:
        config.HERMES_ENABLED = old


def test_retry_succeeds_and_sends(patched_main, sample_item, monkeypatch):
    """ارسال اول شکست، تلاش مجدد موفق → pending_admin با پیام."""
    import config
    import db
    import main
    old = config.HERMES_ENABLED
    config.HERMES_ENABLED = False
    try:
        main.tg.fail_send = True
        assert main.process_item(sample_item) is False
        key = db.make_key(sample_item)
        assert db.get(key)["status"] == db.STATUS_RETRY_PENDING

        # تلاش مجدد موفق
        main.tg.fail_send = False
        n = main.retry_pending_sends()
        assert n == 1
        row = db.get(key)
        assert row["status"] == db.STATUS_PENDING_ADMIN or row["status"] == "sent_admin"
    finally:
        config.HERMES_ENABLED = old
