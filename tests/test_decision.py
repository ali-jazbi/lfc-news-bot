"""تست‌های سیاست تصمیم (مرحله ۱۳/۱۴): reject فقط برای بی‌ربطی قطعی،
review برای ابهام/rumour/اعتماد کم، publish فقط با کیفیت مناسب.
و قوانین محافظه‌کارانه برای ادعاهای مهم."""
import pytest

from ai.editor import deterministic_analysis, tier_of, NewsEditor
from ai.schemas import NewsAnalysis


def _item(**kw):
    base = {"source": "Twitter", "source_tag": "Unknown", "url": "https://x.com/1",
            "handle": "@x", "title": "t", "body": "b", "image": None}
    base.update(kw)
    return base


# ------------------------------------------------------------- policy
def test_reject_only_when_clearly_irrelevant():
    """خبر کاملاً بی‌ربط → reject."""
    item = _item(title="Apple announces new iPhone",
                 body="Apple has announced its latest iPhone with AI features.")
    a = deterministic_analysis(item, tier=tier_of(item))
    assert a.decision == "reject"


def test_unrelated_football_rejected():
    """فوتبال ولی غیر-لیورپول → reject."""
    item = _item(title="Everton close in on new striker signing",
                 body="Everton are close to signing a new striker. The deal is expected soon.")
    a = deterministic_analysis(item, tier=tier_of(item))
    assert a.decision == "reject"


def test_rumour_goes_review():
    """rumour → review نه publish."""
    item = _item(title="Liverpool linked with Kvaratskhelia",
                 body="Reports suggest Liverpool are interested in the winger. Nothing agreed yet.")
    a = deterministic_analysis(item, tier=tier_of(item))
    assert a.decision == "review"
    assert a.needs_verification


def test_official_news_publish():
    item = _item(title="Liverpool confirm new contract for Mohamed Salah",
                 body="Liverpool Football Club is delighted to confirm Mohamed Salah has signed.",
                 source="LFC Official", source_tag="Liverpool FC",
                 url="https://www.liverpoolfc.com/news/1")
    a = deterministic_analysis(item, tier=tier_of(item))
    assert a.decision == "publish"


def test_high_importance_non_official_requires_verification():
    """ادعای مهم از منبع غیررسمی (حتی معتبر) → verification اجباری → review."""
    item = _item(title="Breaking: Salah suffers hamstring injury in training",
                 body="Salah has suffered a hamstring injury in training and could miss three weeks.",
                 source="Sky Sports", source_tag="Sky Sports",
                 url="https://www.skysports.com/1")
    a = deterministic_analysis(item, tier=tier_of(item))
    assert a.decision == "review"
    assert a.needs_verification


def test_confirmed_transfer_from_trusted_publish():
    """انتقال تأییدشده از منبع معتبر → publish (استثنای سیاست)."""
    item = _item(title="Liverpool complete £60m signing of French forward",
                 body="Liverpool have completed the £60m signing on a six-year contract.",
                 source="Sky Sports", source_tag="Sky Sports",
                 url="https://www.skysports.com/1")
    a = deterministic_analysis(item, tier=tier_of(item))
    assert a.decision == "publish"


def test_opinion_rejected():
    item = _item(title="Why Liverpool should sell Salah this summer",
                 body="In my opinion Liverpool should sell Salah and reinvest the money.")
    a = deterministic_analysis(item, tier=tier_of(item))
    assert a.decision == "reject"
    assert a.category == "opinion"


def test_clickbait_rejected():
    item = _item(title="You won't believe what Liverpool's new signing looks like now",
                 body="Click here to see the incredible transformation!")
    a = deterministic_analysis(item, tier=tier_of(item))
    assert a.decision == "reject"


def test_old_news_rejected():
    item = _item(title="Liverpool 4-0 Barcelona - Full match report from 2019",
                 body="Relive the famous comeback victory from that night at Anfield.")
    a = deterministic_analysis(item, tier=tier_of(item))
    assert a.decision == "reject"
    assert a.quality == "outdated"


def test_rumour_from_official_source_review():
    """باشگاه هم گاهی بازتاب گزارش رسانه‌هاست → محتوای rumour = review."""
    item = _item(title="Liverpool in dreamland as PSG slash Bradley Barcola asking price",
                 body="PSG are ready to drop their asking price, according to multiple reports.",
                 source="LFC Official", source_tag="Liverpool FC",
                 url="https://www.liverpoolfc.com/news/1")
    a = deterministic_analysis(item, tier=tier_of(item))
    assert a.decision == "review"


# ------------------------------------------------------------- high impact + low confidence
def test_high_impact_low_confidence_never_publish(fake_hermes, monkeypatch,
                                                  sample_item):
    monkeypatch.setattr("config.AI_ALWAYS_ANALYZE", True)
    fake_hermes.analysis = NewsAnalysis(
        decision="publish", confidence=0.3, importance=9,
        category="breaking", relevance=True, quality="real", tier="medium")
    editor = NewsEditor(client=fake_hermes)
    a = editor.analyze(sample_item)
    assert a.decision == "review"


def test_source_health_degrades_confidence(fake_hermes, monkeypatch, tmp_db,
                                           sample_item):
    """منبع degraded → اعتماد کمتر و شاید review."""
    monkeypatch.setattr("config.AI_ALWAYS_ANALYZE", True)
    monkeypatch.setattr("config.AI_IMPORTANCE_HIGH", 7)
    tmp_db.record_source_health("Fabrizio Romano", ok=False)
    tmp_db.record_source_health("Fabrizio Romano", ok=False)
    fake_hermes.analysis = NewsAnalysis(
        decision="publish", confidence=0.75, importance=8,
        category="transfer_rumour", quality="real", needs_verification=True,
        tier="medium")
    editor = NewsEditor(client=fake_hermes)
    a = editor.analyze(sample_item)
    # degraded → confidence کم شد و review شد (ادعای مهم)
    assert a.confidence < 0.75


def test_hard_rules_override_ai(monkeypatch):
    """قواعد قطعی کانال (women/SKIP/قدیمی) باید حتی publish قاطع AI را
    override کنند — Hermes قواعد کانال را نمی‌داند."""
    import config
    old = config.HERMES_ENABLED
    config.HERMES_ENABLED = True
    try:
        class AlwaysPublish:
            def analyze(self, item, tier="medium"):
                return NewsAnalysis(decision="publish", confidence=1.0,
                                    importance=9, category="player_news",
                                    relevance=True, quality="real",
                                    reason="looks great", tier=tier)

        editor = NewsEditor(client=AlwaysPublish())
        women = _item(title="Liverpool Women sign England midfielder",
                      body="Liverpool Women have completed the signing.")
        assert editor.analyze(women).decision == "reject"
        old_news = _item(title="Van Dijk signs new Liverpool contract - 2024",
                         body="Van Dijk signed in 2024.")
        assert editor.analyze(old_news).decision == "reject"
        gallery = _item(title="Gallery: Liverpool train ahead of clash",
                        body="Photos from the session.")
        assert editor.analyze(gallery).decision == "reject"
        opinion = _item(title="Why Liverpool should sell Salah this summer",
                        body="In my opinion the club should sell.")
        assert editor.analyze(opinion).decision == "reject"
    finally:
        config.HERMES_ENABLED = old
