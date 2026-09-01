"""تست end-to-end (مرحله ۱۶):

سناریوی موفق: Fake RSS → collector → dedup → Hermes mock → ترجمه mock →
عکس mock → Telegram mock → تایید ادمین → منتشر شد.

سناریوی شکست: RSS خراب → fallback → AI موفق → ترجمه شکست → retry →
رسانه موفق → Telegram شکست → retry → publish.
"""
import pytest

import db as dbmod
from ai.schemas import NewsAnalysis, TranslationReview, ImageSelection
from tests.conftest import FakeTelegram  # noqa: F401


@pytest.fixture()
def fake_source_item():
    return {
        "source": "BBC Sport",
        "source_tag": "BBC Sport",
        "url": "https://bbc.co.uk/sport/liverpool-1",
        "title": "Liverpool agree deal for new midfielder",
        "body": ("Liverpool have agreed a deal to sign a new midfielder. The "
                 "club confirmed the transfer on Thursday morning."),
        "image": None,
    }


def test_admin_followup_message_is_not_whitespace_only(monkeypatch, tmp_db, fake_tg,
                                                      fake_source_item):
    """پیام دکمه‌ی ادمین نباید فقط فاصله یا whitespace باشد؛ تلگرام آن را خالی می‌بیند."""
    import config
    import main

    old = config.HERMES_ENABLED
    config.HERMES_ENABLED = False
    try:
        monkeypatch.setattr(main, "tg", fake_tg)
        monkeypatch.setattr(main.translate, "translate",
                            lambda item: {
                                "title": "عنوان", "body": "متن",
                                "importance": "normal", "tags": []})
        monkeypatch.setattr(main.channel_guard, "check",
                            lambda tr, item=None: None)

        assert main.process_item(fake_source_item) is True
        assert all((text or "").strip() for text in fake_tg.sent_messages)
    finally:
        config.HERMES_ENABLED = old


def test_e2e_happy_path(monkeypatch, tmp_db, fake_tg, fake_source_item):
    """Fake RSS → … → تایید ادمین → منتشر شد."""
    import config
    import main

    # 1) HERMES روشن + سردبیر فیک (publish)
    old = config.HERMES_ENABLED
    config.HERMES_ENABLED = True
    try:
        monkeypatch.setattr(main, "tg", fake_tg)

        from tests.conftest import FakeHermesClient
        fake_hermes = FakeHermesClient(
            analysis=NewsAnalysis(
                decision="publish", confidence=0.9, importance=8,
                category="transfer", relevance=True, quality="real",
                reason="confirmed deal", tier="medium"),
            review=TranslationReview(ok=True, score=0.95, issues=[]),
        )

        class FakeEditor:
            def __init__(self):
                self.client = fake_hermes

            def analyze(self, item):
                return fake_hermes.analyze(item)

            def needs_verification(self, analysis, item):
                return False

            def verify(self, item, analysis):
                from ai.schemas import VerificationResult
                return VerificationResult(confidence=0.8, verified=True,
                                          evidence=[{"source": "BBC",
                                                     "url": "https://bbc/1"}],
                                          claim=item["title"])

        monkeypatch.setattr(main, "_get_editor", FakeEditor)
        monkeypatch.setattr(main.translate, "translate",
                            lambda item: {
                                "title": "لیورپول با هافبک جدید به توافق رسید",
                                "body": ("لیورپول با یک هافبک جدید به توافق "
                                         "رسیده و باشگاه صبح پنجشنبه این "
                                         "انتقال را تأیید کرده است."),
                                "importance": "normal", "tags": []})
        monkeypatch.setattr(main.channel_guard, "check",
                            lambda tr, item=None: None)

        # 2) source فیک از طریق collect
        def fake_sources():
            return [("bbc", "خبرگزاری", lambda limit=6: [fake_source_item])]

        monkeypatch.setattr(main, "_sources", fake_sources)

        # 3) سیکل واقعی
        items = main.collect()
        assert len(items) == 1
        key = dbmod.make_key(items[0])
        assert main.process_item(items[0]) is True
        row = dbmod.get(key)
        assert row["status"] == dbmod.STATUS_PENDING_ADMIN
        assert row.get("analysis")  # تحلیل AI ذخیره شد

        # 4) تایید ادمین → منتشر شد
        config.PUBLISH_MODE = "manual"
        config.CHANNEL_ID = ""
        ok, _ = main.approve(key, -100)
        assert ok
        assert dbmod.get(key)["status"] == "approved"
        # 5) (در حالت انتشار در کانال → published)
        config.PUBLISH_MODE = "auto"
        config.CHANNEL_ID = "-100123"
        ok, _ = main.send_to_channel(key)
        assert ok
        assert dbmod.get(key)["status"] == "published"
    finally:
        config.HERMES_ENABLED = old


def test_e2e_failure_scenario(monkeypatch, tmp_db, fake_tg, fake_source_item):
    """RSS خراب → fallback → AI موفق → Telegram شکست → retry → publish."""
    import config
    import main

    old = config.HERMES_ENABLED
    config.HERMES_ENABLED = True
    try:
        monkeypatch.setattr(main, "tg", fake_tg)

        from tests.conftest import FakeHermesClient
        fake_hermes = FakeHermesClient(
            analysis=NewsAnalysis(
                decision="publish", confidence=0.8, importance=7,
                category="player_news", relevance=True, quality="real",
                reason="ok", tier="medium"),
            review=TranslationReview(ok=True, score=0.9, issues=[]),
        )

        class FakeEditor:
            def __init__(self):
                self.client = fake_hermes

            def analyze(self, item):
                return fake_hermes.analyze(item)

            def needs_verification(self, analysis, item):
                return False

            def verify(self, item, analysis):
                from ai.schemas import VerificationResult
                return VerificationResult(confidence=0.5, verified=False,
                                          evidence=[], claim="")

        monkeypatch.setattr(main, "_get_editor", FakeEditor)
        monkeypatch.setattr(main.translate, "translate",
                            lambda item: {
                                "title": "عنوان", "body": "متن",
                                "importance": "normal", "tags": []})
        monkeypatch.setattr(main.channel_guard, "check",
                            lambda tr, item=None: None)

        # منبع اول خراب، منبع دوم (fallback) موفق
        def fake_sources():
            def bad(limit=6):
                raise ConnectionError("rss down")

            def good(limit=6):
                return [fake_source_item]

            return [("dead_rss", "مرده", bad), ("fallback_rss", "پشتیبان", good)]

        monkeypatch.setattr(main, "_sources", fake_sources)
        items = main.collect()
        assert len(items) == 1  # fallback جواب داد

        # 1) تلگرام شکست → retry_pending
        fake_tg.fail_send = True
        assert main.process_item(items[0]) is False
        key = dbmod.make_key(items[0])
        assert dbmod.get(key)["status"] == dbmod.STATUS_RETRY_PENDING

        # 2) تلگرام درست شد → retry موفق → pending_admin
        fake_tg.fail_send = False
        n = main.retry_pending_sends(limit=5)
        assert n == 1
        assert dbmod.get(key)["status"] == dbmod.STATUS_PENDING_ADMIN

        # 3) تایید → منتشر شد
        config.PUBLISH_MODE = "manual"
        ok, _ = main.approve(key, -100)
        assert ok
        assert dbmod.get(key)["status"] == "approved"
    finally:
        config.HERMES_ENABLED = old


def test_e2e_hermes_off_legacy_path(monkeypatch, tmp_db, fake_tg,
                                    fake_source_item):
    """HERMES خاموش → رفتار قبلی: ترجمه + ارسال مستقیم (بدون مراحل AI)."""
    import config
    import main
    old = config.HERMES_ENABLED
    config.HERMES_ENABLED = False
    try:
        monkeypatch.setattr(main, "tg", fake_tg)
        monkeypatch.setattr(main.translate, "translate",
                            lambda item: {
                                "title": "عنوان", "body": "متن",
                                "importance": "normal", "tags": []})
        monkeypatch.setattr(main.channel_guard, "check",
                            lambda tr, item=None: None)
        assert main.process_item(fake_source_item) is True
        key = dbmod.make_key(fake_source_item)
        assert dbmod.get(key)["status"] == "sent_admin"
        assert dbmod.get_analysis(key) is None  # بدون تحلیل AI
    finally:
        config.HERMES_ENABLED = old


# --------------------- آیتم بدون متن قابل‌ترجمه (فقط ایموجی / مدیا) — توییت لیورپول ⏳
def test_process_item_emoji_only_admin_link_passes_through(patched_main, sample_item):
    """لینک ادمین با کپشن ایموجی‌محض → بدون ترجمه passthrough، بدون آلارم."""
    import main
    emoji_item = dict(sample_item, title="⏳️", body="⏳️",
                      url="https://x.com/LFC/status/2094408408451485713")
    calls = {"n": 0}

    def _must_not_run(item):
        calls["n"] += 1
        return {"title": "x", "body": "y"}

    import pytest
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(main.translate, "translate", _must_not_run)
        assert main.process_item(emoji_item, force=True) is True
        assert calls["n"] == 0, "برای متن بدون حرف ترجمه صدا خورد"
    finally:
        monkeypatch.undo()
    assert any("⏳" in m for m in main.tg.sent_messages), "پیش‌نمایش باید با متن اصلی ساخته می‌شد"


def test_process_item_sends_all_videos_locally(patched_main, sample_item, monkeypatch):
    """آیتم با ۲ ویدیو (و یوزربات خاموش) → آلبوم ویدیویی با یک کپشن مشترک ارسال می‌شود."""
    import config
    import main
    monkeypatch.setattr(config, "ENABLE_USERBOT_VIDEOS", False)
    two_vid = dict(sample_item,
                   url="https://x.com/LFC/status/2094077685064716457",
                   video_url="https://video.twimg.com/one.mp4",
                   video_urls=["https://video.twimg.com/one.mp4",
                               "https://video.twimg.com/two.mp4"])
    assert main.process_item(two_vid, force=True) is True
    albums = [c for c in main.tg.calls if c[0] == "send_media_group"]
    assert len(albums) == 1, [c for c in main.tg.calls]
    assert albums[0][2] == 2
    assert albums[0][3] == "video"
    assert albums[0][4] and "عنوان فارسی" in albums[0][4]
    assert any(c[0] == "send_message" for c in main.tg.calls)


def test_process_item_admin_link_translation_failure_still_drafts(patched_main, sample_item, monkeypatch):
    """لینک ادمین + شکست کامل ترجمه → پیش‌نویس با متن اصلی ساخته می‌شود (ویدیو نمی‌میرد)."""
    import main

    def _fail(item):
        return None

    monkeypatch.setattr(main.translate, "translate", _fail)
    ok = main.process_item(sample_item, force=True)
    assert ok is True, "لینک ادمین نباید به‌خاطر شکست ترجمه کامل رد شود"
    assert main.tg.sent_messages, "پیش‌نویس باید با متن اصلی ساخته می‌شد"


def test_process_item_emoji_only_organic_skips_silently(patched_main, sample_item):
    """آیتم ارگانیک بدون متن → رد بی‌سروصدا — نه ترجمه، نه آلارم."""
    import main
    import pytest
    emoji_item = dict(sample_item, title="⏳️", body="⏳️",
                      url="https://x.com/LFC/status/999")
    calls = {"n": 0}
    emoji_item = dict(sample_item, title="⏳️", body="⏳️",
                      url="https://x.com/LFC/status/999")
    calls = {"n": 0}

    def _must_not_run(item):
        calls["n"] += 1
        return {"title": "x", "body": "y"}

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(main.translate, "translate", _must_not_run)
        assert main.process_item(emoji_item) is False
        assert calls["n"] == 0
    finally:
        monkeypatch.undo()
    assert not any("⏳" in m for m in main.tg.sent_messages)
