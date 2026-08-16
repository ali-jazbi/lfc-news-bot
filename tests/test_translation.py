"""تست‌های QC ترجمه (مرحله ۶/۱۵)."""
import pytest

from ai.quality_control import check_facts, translate_with_qc
from ai.schemas import TranslationReview


TR = {
    "title": "لیورپول با محمد صلاح قرارداد بست",
    "body": ("لیورپول با محمد صلاح برای تمدید قرارداد به توافق رسید. باشگاه "
             "اعلام کرد که این بازیکن برای پنج سال دیگر در آنفیلد می‌ماند و "
             "قرارداد جدید او تا پایان فصل ۲۰۳۰ اعتبار دارد. هواداران از این "
             "خبر استقبال کردند و امیدوارند این تمدید به موفقیت تیم در رقابت‌های "
             "این فصل کمک کند. سرمربی نیز از این تصمیم ابراز خرسندی کرد."),
}


def test_correct_translation_no_issues():
    src = ("Liverpool have agreed a new contract with Mohamed Salah. The club "
           "confirmed the forward will stay at Anfield for another five years "
           "and the new deal runs until the end of the 2030 season.")
    issues = check_facts(src, TR)
    assert issues == []


def test_title_wrong_name_detected():
    """نامِ مهمِ متن اصلی (در ۲۰۰ کاراکتر اول = عنوان خبر) باید در عنوان
    ترجمه‌شده هم باشد — عنوان QC می‌شود نه فقط بدنه."""
    src = "Virgil van Dijk signs new Liverpool contract"
    tr = dict(TR)
    tr["title"] = "محمد صلاح قرارداد جدیدی امضا کرد"
    issues = check_facts(src, tr)
    assert any("van dijk" in i.lower() and "title" in i for i in issues)


def test_title_number_only_in_body_is_fine():
    """عدد ۲۰۳۰ در بدنهٔ ترجمه هست و در عنوان نیست — عنوان مشکل ندارد چون
    عدد مهم در کل ترجمه موجود است (چک ۱ پاس می‌کند)."""
    src = ("Liverpool have agreed a new contract with Mohamed Salah. The club "
           "confirmed the forward will stay at Anfield for another five years "
           "and the new deal runs until the end of the 2030 season.")
    tr = dict(TR)
    tr["title"] = "لیورپول با صلاح به توافق رسید"
    issues = check_facts(src, tr)
    assert not any("title" in i for i in issues)


def test_wrong_number_detected():
    src = ("Liverpool agreed a deal worth 71 million euros for the forward.")
    tr = dict(TR)
    tr["body"] = "لیورپول برای این بازیکن ۱۷ میلیون یورو پرداخت کرد."
    issues = check_facts(src, tr)
    assert any("71" in i for i in issues)


def test_wrong_name_detected():
    src = ("Virgil van Dijk signed a new contract with Liverpool.")
    tr = dict(TR)
    tr["body"] = "محمد صلاح قرارداد جدیدی با لیورپول امضا کرد."
    issues = check_facts(src, tr)
    assert any("van dijk" in i.lower() for i in issues)


def test_missing_facts_detected():
    src = ("Liverpool confirmed 47 million transfer fee for the new signing.")
    tr = dict(TR)
    tr["body"] = "لیورپول بازیکن جدیدی خرید."
    issues = check_facts(src, tr)
    assert any("47" in i for i in issues)


def test_latin_leftover_detected():
    src = "Liverpool signed a player from Real Madrid."
    tr = dict(TR)
    tr["body"] = "لیورپول بازیکنی از Real Madrid خرید."
    issues = check_facts(src, tr)
    assert any("latin" in i for i in issues)


def test_hallucination_detected_by_review(fake_hermes, monkeypatch, sample_item):
    """ترجمه شامل محتوای جعلی → review ok=False → اصلاح."""
    monkeypatch.setattr("config.HERMES_ENABLED", True)
    from ai.editor import NewsEditor
    editor = NewsEditor(client=fake_hermes)
    fake_hermes.review = TranslationReview(
        ok=False, score=0.3,
        issues=["invented quote: «رومانو گفت...»"],
        revision="نسخه اصلاح‌شده که فقط محتوای اصلی را دارد و چیزی جعل نشده است."
                 " این متن به اندازه کافی طولانی است که از حداقل طول عبور کند.",
    )
    tr, review, human = translate_with_qc(sample_item, editor, tr=TR)
    assert review.issues
    assert review.revision


def test_max_revision_limit(fake_hermes, monkeypatch, sample_item):
    """بعد از MAX_REVISIONS بار اصلاح و هنوز بد → human_review."""
    monkeypatch.setattr("config.HERMES_ENABLED", True)
    monkeypatch.setattr("config.HERMES_MAX_REVISIONS", 2)
    from ai.editor import NewsEditor
    editor = NewsEditor(client=fake_hermes)

    # همیشه بد برمی‌گردد
    fake_hermes.review = TranslationReview(
        ok=False, score=0.2, issues=["bad quality"], revision="اصلاح")

    tr, review, human = translate_with_qc(sample_item, editor, tr=TR)
    assert human  # بعد از سقف → human_review
    assert len([c for c in fake_hermes.calls if c[0] == "review_translation"]) == 3


def test_translate_qc_ai_disabled_deterministic_only(monkeypatch, sample_item):
    """HERMES خاموش → فقط چک قطعی، بدون بازبینی AI."""
    monkeypatch.setattr("config.HERMES_ENABLED", False)
    tr, review, human = translate_with_qc(sample_item, tr=TR)
    assert review.ok is True or review.issues  # قطعی فقط


def test_translate_qc_style_examples_used(fake_hermes, monkeypatch, sample_item,
                                          tmp_db):
    """نمونه‌های کانال به reviewer داده می‌شود."""
    monkeypatch.setattr("config.HERMES_ENABLED", True)
    # یک پست منتشرشده در DB
    import db
    p = dict(sample_item)
    p["translated"] = TR
    db.save(p, status="published")
    from ai.editor import NewsEditor
    editor = NewsEditor(client=fake_hermes)
    translate_with_qc(sample_item, editor, tr=TR)
    rv_calls = [c for c in fake_hermes.calls if c[0] == "review_translation"]
    assert rv_calls and rv_calls[0][1] >= 1  # حداقل یک مثال کانال داده شد
