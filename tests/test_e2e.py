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
