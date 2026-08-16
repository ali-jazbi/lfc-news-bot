"""تست‌های لایه AI (مرحله ۱۵): تصمیم‌ها، اعتماد پایین، راستی‌آزمایی،
خروجی خراب، timeout، خطای provider."""
import json

import pytest

from ai.editor import NewsEditor, tier_of, deterministic_analysis
from ai.schemas import NewsAnalysis, SchemaError, VerificationResult


def _editor_with(client):
    return NewsEditor(client=client)


# ------------------------------------------------------------- tier
def test_tier_official_is_low(official_item):
    assert tier_of(official_item) == "low"


def test_tier_unknown_transfer_is_high(sample_item):
    item = dict(sample_item)
    item["handle"] = "@unknown_journalist"
    assert tier_of(item) == "high"


def test_tier_trusted_journalist_transfer_medium(sample_item):
    assert tier_of(sample_item) == "medium"  # Fabrizio Romano (tier1)


# ------------------------------------------------------------- analyze
def test_ai_publish_decision(fake_hermes, monkeypatch, official_item):
    monkeypatch.setattr("config.AI_ALWAYS_ANALYZE", True)
    fake_hermes.analysis = NewsAnalysis(
        decision="publish", confidence=0.9, importance=8,
        category="transfer", relevance=True, quality="real",
        reason="confirmed by club", tier="medium")
    editor = _editor_with(fake_hermes)
    a = editor.analyze(official_item)
    assert a.decision == "publish"
    assert a.importance == 8


def test_ai_reject_decision(fake_hermes, monkeypatch, irrelevant_item):
    monkeypatch.setattr("config.AI_ALWAYS_ANALYZE", True)
    fake_hermes.analysis = NewsAnalysis(
        decision="reject", confidence=0.95, importance=1,
        category="irrelevant", relevance=False, quality="misleading",
        reason="not about Liverpool", tier="medium")
    editor = _editor_with(fake_hermes)
    a = editor.analyze(irrelevant_item)
    assert a.decision == "reject"


def test_ai_review_decision(fake_hermes, monkeypatch, sample_item):
    monkeypatch.setattr("config.AI_ALWAYS_ANALYZE", True)
    fake_hermes.analysis = NewsAnalysis(
        decision="review", confidence=0.5, importance=6,
        category="transfer_rumour", relevance=True, quality="speculation",
        reason="rumour", needs_verification=True, tier="medium")
    editor = _editor_with(fake_hermes)
    a = editor.analyze(sample_item)
    assert a.decision == "review"
    assert a.needs_verification


def test_ai_low_confidence_downgrades_to_review(fake_hermes, monkeypatch,
                                                sample_item):
    """اهمیت بالا + اعتماد پایین → publish نمی‌شود (review می‌شود)."""
    monkeypatch.setattr("config.AI_ALWAYS_ANALYZE", True)
    fake_hermes.analysis = NewsAnalysis(
        decision="publish", confidence=0.3, importance=9,
        category="breaking", relevance=True, quality="real",
        reason="confident but low score", tier="medium")
    editor = _editor_with(fake_hermes)
    a = editor.analyze(sample_item)
    assert a.decision == "review"


def test_ai_speculation_never_auto_publish(fake_hermes, monkeypatch,
                                           sample_item):
    monkeypatch.setattr("config.AI_ALWAYS_ANALYZE", True)
    fake_hermes.analysis = NewsAnalysis(
        decision="publish", confidence=0.9, importance=7,
        category="transfer_rumour", relevance=True, quality="speculation",
        reason="speculative", tier="medium")
    editor = _editor_with(fake_hermes)
    a = editor.analyze(sample_item)
    assert a.decision == "review"  # speculation هرگز publish خودکار


# ------------------------------------------------------------- fallback
def test_ai_provider_failure_falls_back(fake_hermes, monkeypatch, sample_item):
    """خطای provider → تحلیل قطعی (بدون کرش)."""
    monkeypatch.setattr("config.AI_ALWAYS_ANALYZE", True)
    fake_hermes.fail = True
    editor = _editor_with(fake_hermes)
    a = editor.analyze(sample_item)
    assert a.decision in ("publish", "review", "reject")
    assert a.tier == "medium"


def test_deterministic_rejects_noise(irrelevant_item):
    a = deterministic_analysis(irrelevant_item, tier="medium")
    assert a.decision == "reject"


# ------------------------------------------------------------- verification
def test_needs_verification_suspicious(fake_hermes, sample_item):
    fake_hermes.analysis = NewsAnalysis(decision="review", confidence=0.5,
                                        importance=8, category="transfer_rumour",
                                        needs_verification=True)
    editor = _editor_with(fake_hermes)
    assert editor.needs_verification(fake_hermes.analysis, sample_item)


def test_verification_with_evidence_sets_confident(fake_hermes, monkeypatch,
                                                   tmp_db, sample_item):
    monkeypatch.setattr("config.AI_ALWAYS_ANALYZE", True)
    ev = [{"source": "BBC", "title": "t1", "url": "https://bbc/1"},
          {"source": "Sky", "title": "t2", "url": "https://sky/2"}]
    fake_hermes.analysis = NewsAnalysis(
        decision="review", confidence=0.6, importance=8,
        category="transfer_rumour", needs_verification=True, tier="medium")
    fake_hermes.verification = VerificationResult(
        confidence=0.85, verified=True, evidence=ev, claim="c", checked_at=0)
    monkeypatch.setattr("ai.editor.collect_evidence", lambda item, claim: list(ev))
    editor = _editor_with(fake_hermes)
    a = editor.analyze(sample_item)
    key = tmp_db.save(sample_item)  # در prod قبل از verify ذخیره شده
    vr = editor.verify(sample_item, a)
    assert vr.verified
    assert vr.confidence == 0.85
    # ذخیره شد؟
    row = tmp_db.get(key)
    assert row and row.get("verification")


def test_verification_keeps_collected_evidence_even_if_ai_drops_it(
        fake_hermes, monkeypatch, tmp_db, sample_item):
    """شواهد جمع‌آوری‌شده باید در رکورد ذخیره شود حتی اگر agent آن‌ها را
    در پاسخ JSON بازتاب ندهد (یکپارچگی رکورد verification)."""
    monkeypatch.setattr("config.AI_ALWAYS_ANALYZE", True)
    ev = [{"source": "BBC", "title": "t1", "url": "https://bbc/1"},
          {"source": "Sky", "title": "t2", "url": "https://sky/2"}]
    fake_hermes.analysis = NewsAnalysis(
        decision="review", confidence=0.6, importance=8,
        category="transfer_rumour", needs_verification=True, tier="medium")
    # agent فقط ارزیابی می‌دهد، شواهد را برنمی‌گرداند
    fake_hermes.verification = VerificationResult(
        confidence=0.3, verified=False, evidence=[], claim="c", checked_at=0)
    monkeypatch.setattr("ai.editor.collect_evidence", lambda item, claim: list(ev))
    editor = _editor_with(fake_hermes)
    a = editor.analyze(sample_item)
    tmp_db.save(sample_item)
    vr = editor.verify(sample_item, a)
    assert vr.evidence == ev  # شواهد حفظ شد
    row = tmp_db.get(tmp_db.make_key(sample_item))
    saved = json.loads(row["verification"])
    assert len(saved["evidence"]) == 2


def test_verification_no_evidence_never_verified(fake_hermes, monkeypatch,
                                                 tmp_db, sample_item):
    monkeypatch.setattr("config.AI_ALWAYS_ANALYZE", True)
    fake_hermes.analysis = NewsAnalysis(
        decision="review", confidence=0.6, importance=8,
        category="transfer_rumour", needs_verification=True, tier="medium")
    fake_hermes.verification = VerificationResult(
        confidence=0.95, verified=True, evidence=[], claim="c", checked_at=0)
    monkeypatch.setattr("ai.editor.collect_evidence", lambda item, claim: [])
    editor = _editor_with(fake_hermes)
    a = editor.analyze(sample_item)
    tmp_db.save(sample_item)
    vr = editor.verify(sample_item, a)
    # بدون شواهد → هرگز verified نمی‌شود (ضد-هالوسینیشن)
    assert not vr.verified
    assert vr.confidence <= 0.3


# ------------------------------------------------------------- schema
def test_malformed_ai_response_falls_back(monkeypatch, sample_item):
    monkeypatch.setattr("config.AI_ALWAYS_ANALYZE", True)

    class BadClient:
        def analyze(self, item, tier="medium"):
            raise SchemaError("not an object")

    editor = NewsEditor(client=BadClient())
    a = editor.analyze(sample_item)
    assert a.decision in ("publish", "review", "reject")


def test_schema_rejects_bad_decision():
    a = NewsAnalysis.from_dict({"decision": "maybe", "importance": 5,
                                "confidence": 0.5})
    assert a.decision == "review"  # مقدار نامعتبر → پیش‌فرض محافظه‌کارانه


def test_schema_clamps_importance():
    a = NewsAnalysis.from_dict({"decision": "publish", "importance": 99,
                                "confidence": 0.9})
    assert a.importance == 10


def test_schema_not_relevant_rejects():
    a = NewsAnalysis.from_dict({"decision": "publish", "relevance": False,
                                "confidence": 0.9})
    assert a.decision == "reject"
