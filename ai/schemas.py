"""Schemaهای تحلیل خبر — همه خروجی‌های AI قبل از استفاده validation می‌شوند.

قانون ضد-هالوسینیشن: هیچ فیلدی از مدل بدون بررسی پذیرفته نمی‌شود؛ اگر
schema خراب/ناقص باشد، به‌جای حدس زدن، خطای SchemaError داده می‌شود تا
مسیر fallback (deterministic) کار کند.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ارزش‌های مجاز — اگر مدل چیزی خارج از این‌ها بدهد، رد می‌شود
DECISIONS = ("publish", "review", "reject")
CONTENT_TYPES = (
    "breaking", "transfer", "transfer_rumour", "injury", "lineup", "match",
    "result", "quote", "training", "club_announcement", "player_news",
    "manager_news", "opinion", "speculation", "irrelevant",
)
QUALITIES = (
    "real", "speculation", "opinion", "clickbait", "duplicate",
    "outdated", "misleading",
)
TIERS = ("low", "medium", "high")

# کلماتی که یعنی «ادعای خبری» — برای tier بالا/verification
SUSPICIOUS_SIGNALS = (
    "rumour", "rumor", "reportedly", "according to reports", "could be",
    "expected to", "in talks", "close to", "set to", "linked with", "interested in",
    "bidding", "offer", "sources say", "source says", "claims", "believes",
)

# منابع رسمی/قابل‌اعتماد → tier پایین (تحلیل ارزان‌تر)
TRUSTED_SOURCES = (
    "liverpool fc", "lfc official", "bbc sport", "sky sports", "the guardian",
    "liverpool echo", "the athletic", "espn",
)


class SchemaError(Exception):
    """خروجی AI با schema جور نیست."""


def _clean_str(v, default=""):
    if v is None:
        return default
    s = str(v).strip()
    return s or default


def _to_float(v, default=0.0):
    try:
        f = float(v)
        return max(0.0, min(1.0, f))
    except (TypeError, ValueError):
        return default


def _to_int(v, default=5, lo=1, hi=10):
    try:
        i = int(round(float(v)))
        return max(lo, min(hi, i))
    except (TypeError, ValueError):
        return default


def _in(value, allowed, default, field_name):
    v = _clean_str(value).lower()
    return v if v in allowed else default


@dataclass
class NewsAnalysis:
    """خروجی سردبیر (Hermes) برای یک خبر — مرحله ۴."""

    decision: str = "review"            # publish | review | reject
    confidence: float = 0.0             # 0..1
    importance: int = 5                 # 1..10
    category: str = "player_news"       # از CONTENT_TYPES
    relevance: bool = True
    quality: str = "real"               # از QUALITIES
    reason: str = ""
    needs_verification: bool = False
    verification_summary: Optional[str] = None
    tier: str = "medium"                # low | medium | high
    raw: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """قواعد ایمنی — صرف‌نظر از اینکه آبجکت چطور ساخته شده اعمال می‌شود
        (دفاع عمقی، هم برای خروجی AI و هم برای تست‌ها):
        • اهمیت بالا + اعتماد پایین → هرگز publish خودکار
        • کیفیت مشکوک (speculation/opinion/clickbait/misleading) → review
        • بی‌ربط → reject
        """
        if self.importance >= 7 and self.confidence < 0.5 \
                and self.decision == "publish":
            self.decision = "review"
        if self.quality in ("speculation", "opinion", "clickbait",
                            "misleading") and self.decision == "publish":
            self.decision = "review"
        if not self.relevance and self.decision == "publish":
            self.decision = "reject"

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "confidence": self.confidence,
            "importance": self.importance,
            "category": self.category,
            "relevance": self.relevance,
            "quality": self.quality,
            "reason": self.reason,
            "needs_verification": self.needs_verification,
            "verification_summary": self.verification_summary,
            "tier": self.tier,
        }

    @classmethod
    def from_dict(cls, data: dict, tier: str = "medium") -> "NewsAnalysis":
        """ساخت از دیکشنری خام AI با validation کامل — در صورت خرابی SchemaError."""
        if not isinstance(data, dict):
            raise SchemaError("analysis is not an object")
        decision = _in(data.get("decision"), DECISIONS, "review", "decision")
        category = _in(data.get("category") or data.get("content_type"),
                       CONTENT_TYPES, "player_news", "category")
        quality = _in(data.get("quality"), QUALITIES, "real", "quality")
        confidence = _to_float(data.get("confidence"), 0.0)
        importance = _to_int(data.get("importance"), 5, 1, 10)
        relevance = bool(data.get("relevance", True))
        needs_verification = bool(data.get("needs_verification", False))
        reason = _clean_str(data.get("reason"))[:400]
        summary = data.get("verification_summary")
        summary = _clean_str(summary)[:400] if summary is not None else None

        # اگر مدل «مهم» گفت ولی مطمئن نبود → review تا انسان تصمیم بگیرد
        if importance >= 7 and confidence < 0.5 and decision == "publish":
            decision = "review"
        # کیفیت‌های مشکوک هرگز publish خودکار نمی‌شوند
        if quality in ("speculation", "opinion", "clickbait", "misleading") \
                and decision == "publish":
            decision = "review"
        if not relevance and decision == "publish":
            decision = "reject"

        return cls(
            decision=decision, confidence=confidence, importance=importance,
            category=category, relevance=relevance, quality=quality,
            reason=reason, needs_verification=needs_verification,
            verification_summary=summary, tier=tier, raw=dict(data),
        )


@dataclass
class VerificationResult:
    """نتیجه راستی‌آزمایی — مرحله ۵."""

    confidence: float = 0.0
    verified: bool = False              # شواهد کافی پیدا شد؟
    evidence: List[Dict[str, str]] = field(default_factory=list)
    claim: str = ""
    source: str = ""
    summary: str = ""
    checked_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "confidence": self.confidence,
            "verified": self.verified,
            "evidence": self.evidence,
            "claim": self.claim,
            "source": self.source,
            "summary": self.summary,
            "checked_at": self.checked_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VerificationResult":
        if not isinstance(data, dict):
            raise SchemaError("verification is not an object")
        confidence = _to_float(data.get("confidence"), 0.0)
        verified = bool(data.get("verified", False))
        evidence = data.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = []
        evidence = [
            {k: _clean_str(e.get(k)) for k in ("source", "title", "url", "snippet")}
            for e in evidence if isinstance(e, dict)
        ][:10]
        return cls(
            confidence=confidence, verified=verified, evidence=evidence,
            claim=_clean_str(data.get("claim"))[:400],
            source=_clean_str(data.get("source"))[:100],
            summary=_clean_str(data.get("summary"))[:500],
            checked_at=float(data.get("checked_at") or 0),
        )


@dataclass
class TranslationReview:
    """نتیجه QC ترجمه — مرحله ۶."""

    ok: bool = True
    score: float = 0.9                  # 0..1 کیفیت
    issues: List[str] = field(default_factory=list)
    revision: str = ""                  # متن اصلاح‌شده (در صورت نیاز)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "score": self.score, "issues": self.issues[:8]}

    @classmethod
    def from_dict(cls, data: dict) -> "TranslationReview":
        if not isinstance(data, dict):
            raise SchemaError("translation review is not an object")
        ok = bool(data.get("ok", True))
        score = _to_float(data.get("score"), 0.9)
        issues = data.get("issues") or []
        if not isinstance(issues, list):
            issues = []
        issues = [_clean_str(i)[:200] for i in issues if _clean_str(i)][:8]
        return cls(ok=ok, score=score, issues=issues,
                   revision=_clean_str(data.get("revision"))[:4000])


@dataclass
class ImageSelection:
    """انتخاب عکس — مرحله ۷."""

    image_url: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        return {"image_url": self.image_url, "confidence": self.confidence,
                "reason": self.reason[:200]}

    @classmethod
    def from_dict(cls, data: dict) -> "ImageSelection":
        if not isinstance(data, dict):
            raise SchemaError("image selection is not an object")
        url = _clean_str(data.get("image_url")) or None
        return cls(image_url=url, confidence=_to_float(data.get("confidence")),
                   reason=_clean_str(data.get("reason"))[:300])


def extract_json_object(text: str) -> Optional[dict]:
    """اولین آبجکت JSON را از متن خروجی مدل درمی‌آورد (با تحمل code fence/think)."""
    text = (text or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"<think>.*$", "", text, flags=re.S | re.I)
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start = text.find("{")
    if start == -1:
        return None
    end = text.rfind("}")
    if end == -1 or end < start:
        return None
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None
