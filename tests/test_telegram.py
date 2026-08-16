"""تست‌های Telegram (مرحله ۱۵): ارسال موفق/ناموفق/retry، تایید، انتشار."""
import pytest


def test_process_item_success(patched_main, sample_item):
    """ارسال موفق → status pending_admin (با HERMES) و پیام ثبت می‌شود."""
    import config
    import db
    import main
    old = config.HERMES_ENABLED
    config.HERMES_ENABLED = False  # legacy path
    try:
        assert main.process_item(sample_item) is True
        row = db.get(db.make_key(sample_item))
        assert row["status"] == "sent_admin"
        assert row["admin_msg"]
        assert any("عنوان فارسی" in t for t in main.tg.sent_messages)
    finally:
        config.HERMES_ENABLED = old


def test_process_item_send_failure_retry_pending(patched_main, sample_item):
    """شکست ارسال → retry_pending با خطا (خبر گم نمی‌شود)."""
    import db
    import main
    main.tg.fail_send = True
    assert main.process_item(sample_item) is False
    row = db.get(db.make_key(sample_item))
    assert row["status"] == db.STATUS_RETRY_PENDING
    assert row["error"]


def test_process_item_duplicate_skipped(patched_main, sample_item):
    import db
    import main
    db.save(sample_item, status="sent_admin")
    assert main.process_item(sample_item) is False


def _with_translation(item):
    item = dict(item)
    item["translated"] = {"title": "عنوان", "body": "متن", "importance": "normal"}
    return item


def test_approve_manual_publishes_clean(patched_main, sample_item):
    import config
    import db
    import main
    config.PUBLISH_MODE = "manual"
    key = db.save(_with_translation(sample_item), status="sent_admin")
    ok, msg = main.approve(key, -100)
    assert ok
    assert db.get(key)["status"] == "approved"


def test_approve_auto_publishes_to_channel(patched_main, sample_item):
    import config
    import db
    import main
    config.PUBLISH_MODE = "auto"
    config.CHANNEL_ID = "-100123"
    key = db.save(_with_translation(sample_item), status="sent_admin")
    ok, msg = main.approve(key, -100)
    assert ok
    assert db.get(key)["status"] == "published"


def test_approve_auto_failure(patched_main, sample_item):
    import config
    import db
    import main
    config.PUBLISH_MODE = "auto"
    config.CHANNEL_ID = "-100123"
    key = db.save(_with_translation(sample_item), status="sent_admin")
    main.tg.fail_send = True
    ok, msg = main.approve(key, -100)
    assert not ok


def test_approve_records_feedback(patched_main, sample_item):
    """تایید ادمین → رکورد feedback (مرحله ۱۲)."""
    import config
    import db
    import main
    config.PUBLISH_MODE = "manual"
    key = db.save(_with_translation(sample_item), status="sent_admin")
    db.record_analysis(key, {"decision": "publish", "importance": 7})
    main.approve(key, -100)
    rows = db._c().execute("SELECT * FROM feedback WHERE news_key=?",
                           (key,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["ai_decision"] == "publish"
    assert rows[0]["human_action"] == "approve"


def test_handle_callback_approve(patched_main, sample_item):
    """کلیک دکمه انتشار از طریق callback query."""
    import config
    import db
    import main
    config.PUBLISH_MODE = "manual"
    key = db.save(_with_translation(sample_item), status="sent_admin")
    cq = {"id": "cid1", "data": "pub:" + key,
          "message": {"chat": {"id": -100}, "message_id": 7},
          "from": {"id": 1, "first_name": "admin"}}
    main.handle_callback(cq)
    assert db.get(key)["status"] == "approved"


def test_callback_unknown_news(patched_main):
    import main
    cq = {"id": "cid2", "data": "pub:unknownkey123",
          "message": {"chat": {"id": -100}, "message_id": 8},
          "from": {"id": 1}}
    # نباید کرش کند
    main.handle_callback(cq)
