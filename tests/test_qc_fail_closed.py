"""تست‌های fail-closed QC (مرحله ۷ مأموریت) + gate نهایی ادمین (مرحله ۱۹)."""
import pytest

from ai.quality_control import translate_with_qc, check_facts
from ai.schemas import TranslationReview


TR = {
    "title": "لیورپول با محمد صلاح قرارداد بست",
    "body": ("لیورپول با محمد صلاح برای تمدید قرارداد به توافق رسید. باشگاه "
             "اعلام کرد که این بازیکن برای پنج سال دیگر در آنفیلد می‌ماند و "
             "قرارداد جدید او تا پایان فصل ۲۰۳۰ اعتبار دارد. هواداران از این "
             "خبر استقبال کردند و امیدوارند این تمدید به موفقیت تیم در رقابت‌های "
             "این فصل کمک کند. سرمربی نیز از این تصمیم ابراز خرسندی کرد."),
}


# ------------------------------------------------------------- fail-closed
def test_qc_crash_is_fail_closed(monkeypatch, sample_item):
    """کرش AI QC → available=False + human_review=True — هرگز «خوب است» نمی‌گوید."""
    monkeypatch.setattr("config.HERMES_ENABLED", True)

    class CrashClient:
        def review_translation(self, item, tr, examples):
            raise RuntimeError("provider down")

    from ai.editor import NewsEditor
    editor = NewsEditor(client=CrashClient())
    tr, review, human = translate_with_qc(sample_item, editor, tr=TR)
    assert review.available is False
    assert review.ok is False
    assert human is True


def test_qc_unavailable_review_object():
    r = TranslationReview.unavailable("no keys")
    assert r.available is False
    assert r.ok is False
    assert r.human_review_required is True


def test_qc_normal_review_not_human():
    r = TranslationReview(ok=True, score=0.95, issues=[])
    assert r.human_review_required is False


def test_revision_supports_title_and_body(fake_hermes, monkeypatch, sample_item):
    """اصلاح باید عنوان و بدنه را جدا پشتیبانی کند."""
    monkeypatch.setattr("config.HERMES_ENABLED", True)
    monkeypatch.setattr("config.HERMES_MAX_REVISIONS", 2)
    fake_hermes.review = TranslationReview(
        ok=False, score=0.4, issues=["wrong title"],
        revision_title="عنوان اصلاح‌شده جدید", revision_body="",
    )
    from ai.editor import NewsEditor
    editor = NewsEditor(client=fake_hermes)
    tr, review, human = translate_with_qc(sample_item, editor, tr=dict(TR))
    assert tr["title"] == "عنوان اصلاح‌شده جدید"
    assert tr["body"] == TR["body"]  # body دست نخورد


def test_revision_body_only_keeps_title(fake_hermes, monkeypatch, sample_item):
    monkeypatch.setattr("config.HERMES_ENABLED", True)
    monkeypatch.setattr("config.HERMES_MAX_REVISIONS", 2)
    fake_hermes.review = TranslationReview(
        ok=False, score=0.4, issues=["bad body"],
        revision_title="", revision_body="بدنه اصلاح‌شده که به اندازه کافی طولانی است تا از حداقل طول عبور کند و محتوای اصلی را حفظ کرده است. این متن برای تست در نظر گرفته شده است.",
    )
    from ai.editor import NewsEditor
    editor = NewsEditor(client=fake_hermes)
    tr, review, human = translate_with_qc(sample_item, editor, tr=dict(TR))
    assert tr["title"] == TR["title"]  # title دست نخورد
    assert tr["body"].startswith("بدنه اصلاح‌شده")


def test_revision_limit_reaches_human_review(fake_hermes, monkeypatch, sample_item):
    """بعد از سقف اصلاح و هنوز بد → human_review_required."""
    monkeypatch.setattr("config.HERMES_ENABLED", True)
    monkeypatch.setattr("config.HERMES_MAX_REVISIONS", 2)
    fake_hermes.review = TranslationReview(
        ok=False, score=0.2, issues=["still bad"],
        revision_title="", revision_body="اصلاح")
    from ai.editor import NewsEditor
    editor = NewsEditor(client=fake_hermes)
    tr, review, human = translate_with_qc(sample_item, editor, tr=dict(TR))
    assert human is True
    # ۱ بازبینی اول + ۲ تلاش اصلاح = ۳ فراخوانی
    assert len([c for c in fake_hermes.calls if c[0] == "review_translation"]) == 3


def test_deterministic_issues_flag_ok_false(fake_hermes, monkeypatch, sample_item):
    """چک قطعی (مثلاً عدد گم‌شده) → review.ok=False حتی اگر AI بگوید خوب است."""
    monkeypatch.setattr("config.HERMES_ENABLED", True)
    fake_hermes.review = TranslationReview(ok=True, score=0.95, issues=[])
    from ai.editor import NewsEditor
    editor = NewsEditor(client=fake_hermes)
    bad_src = {"title": "Liverpool complete 71m signing",
               "body": "deal worth 71 million euros"}
    item = dict(sample_item, **bad_src)
    tr = dict(TR)
    tr["body"] = "لیورپول قرارداد ۱۷ میلیون یورویی بست." + " متن اضافی برای طول کافی " * 20
    _, review, human = translate_with_qc(item, editor, tr=tr)
    assert review.ok is False
    assert human is True


# ------------------------------------------------------------- admin gate
def test_admin_approval_still_required_when_ai_confident(patched_main,
                                                         sample_item, fake_tg):
    """حتی با confidence=1.0، انتشار نیاز به approve ادمین دارد (مرحله ۱۹)."""
    import config
    import db
    import main
    old_mode = config.PUBLISH_MODE
    old_chan = config.CHANNEL_ID
    config.PUBLISH_MODE = "auto"
    config.CHANNEL_ID = "@test_channel"
    try:
        item = dict(sample_item)
        item["translated"] = TR
        key = db.make_key(item)
        db.save(item, status=db.STATUS_PENDING_ADMIN)
        db.record_analysis(key, {"decision": "publish", "confidence": 1.0,
                                 "importance": 10, "verified": True})
        # بدون کلیک ادمین، چیزی روی کانال نرفته
        assert not any(c[0] == "send_post" and c[1] == "@test_channel"
                       for c in fake_tg.calls)
        # approve → حالا می‌رود
        ok, msg = main.approve(key, config.ADMIN_CHAT_ID)
        assert ok
        assert any(c[0] == "send_post" and c[1] == "@test_channel"
                   for c in fake_tg.calls)
        assert db.get(key)["status"] == db.STATUS_PUBLISHED
    finally:
        config.PUBLISH_MODE = old_mode
        config.CHANNEL_ID = old_chan
