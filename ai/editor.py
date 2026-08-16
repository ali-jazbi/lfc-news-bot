"""سردبیر خبر (Hermes) — مرحله ۲ تا ۵.

NewsEditor مسئول:
  • tier_of(item)          → کم‌هزینه/عادی/پرهزینه (استراتژی AI، مرحله ۱۳/۱۴/۱۵)
  • analyze(item)          → NewsAnalysis (relevance/نوع/کیفیت/اهمیت/تصمیم)
  • needs_verification()   → آیا این خبر باید راستی‌آزمایی شود؟
  • verify(item, analysis) → جمع‌آوری شواهد + ارزیابی + ذخیره VerificationResult

قانون مهم: اگر AI در دسترس نباشد یا schema خراب باشد، هرگز bot down نمی‌شود —
deterministic_analysis() (همان منطق کلمه‌ای/منبع فعلی، اما ساختاریافته) جواب
می‌دهد. هزینه: tier پایین → یک فراخوانی ارزان؛ tier بالا → agent + شواهد.
"""
from __future__ import annotations

import logging
import re
import time

import config
import db

from .schemas import (
    NewsAnalysis, VerificationResult, SchemaError,
    SUSPICIOUS_SIGNALS, TRUSTED_SOURCES, TIERS,
)
from .tracing import trace, news_id_of

log = logging.getLogger("ai.editor")

# حساب‌های خبرنگار اصلی (tier1) — قابل‌اعتمادتر از حساب‌های ناشناس
_TIER1_HANDLES = {"fabrizioromano", "david_ornstein", "jamespearcelfc",
                  "davidlynchlfc", "_pauljoyce", "lfc"}

# کلماتی که یعنی «خبر رسمی باشگاه»
_OFFICIAL_SIGNALS = ("official", "confirmed by the club", "liverpoolfc.com",
                     "statement", "announcement")

# الگوهای خبر مهم (importance بالا)
_HIGH_SIGNALS = (
    "here we go", "official", "confirmed", "medical", "release clause",
    "agreement", "agreed", "signs", "signed", "injury", "ruled out",
    "exclusive", "breaking", "lineup", "team news", "contract extension",
)


def _source_key(item: dict) -> str:
    return (item.get("source_tag") or item.get("source") or "").strip().lower()


def _is_official(item: dict) -> bool:
    src = _source_key(item)
    url = (item.get("url") or "").lower()
    return ("liverpool fc" in src or "lfc official" in src
            or "liverpoolfc.com" in url)


def _is_trusted_outlet(item: dict) -> bool:
    src = _source_key(item)
    return any(t in src for t in TRUSTED_SOURCES)


def _handle(item: dict) -> str:
    return (item.get("handle") or "").strip().lstrip("@").lower()


def _blob(item: dict) -> str:
    return (((item.get("title") or "") + " " + (item.get("body") or ""))
            .lower())


def tier_of(item: dict) -> str:
    """استراتژی سه‌سطحی (مرحله ۱۳/۱۴/۱۵):

    low    → منبع رسمی باشگاه یا خبرگزاری معتبر (بیانیه/خبر رسمی)
    high   → ادعای مهم از حساب غیررسمی، rumour، نقل‌وانتقال از منبع ناشناس
    medium → بقیه
    """
    blob = _blob(item)
    if _is_official(item):
        return "low"
    if _is_trusted_outlet(item):
        return "low"
    # ادعای مهم (transfer/injury/breaking) از حساب‌های ناشناس → عمیق‌ترین بررسی
    handle = _handle(item)
    is_breaking = any(s in blob for s in
                      ("transfer", "injury", "ruled out", "here we go",
                       "breaking", "exclusive", "medical", "signs", "agreed"))
    if is_breaking and handle and handle not in _TIER1_HANDLES:
        return "high"
    if any(s in blob for s in SUSPICIOUS_SIGNALS):
        return "high"
    if item.get("priority") or any(s in blob for s in _HIGH_SIGNALS):
        return "medium"
    return "medium"


def deterministic_analysis(item: dict, tier: str = "medium") -> NewsAnalysis:
    """Fallback قطعی — همان منطق کلمه‌ای فعلی بات، اما در قالب NewsAnalysis.

    بدون هیچ هزینه AI؛ فقط برای وقتی Hermes/LLM در دسترس نیست یا خراب است.
    محافظه‌کار است: هر ابهامی → review (انسان تصمیم می‌گیرد).
    """
    blob = _blob(item)
    title = (item.get("title") or "").lower()

    # نویزهای قطعی (فیلتر فعلی SKIP_KEYWORDS + is_noise)
    for kw in getattr(config, "SKIP_KEYWORDS", []):
        if kw and kw.lower() in title:
            return NewsAnalysis(
                decision="reject", confidence=0.95, importance=1,
                category="irrelevant", relevance=False, quality="clickbait",
                reason=f"skip keyword: {kw}", tier=tier,
            )
    if not config.INCLUDE_WOMEN and re.search(r"women|wsl", blob):
        return NewsAnalysis(
            decision="reject", confidence=0.9, importance=1,
            category="irrelevant", relevance=False, quality="outdated",
            reason="women's team not covered", tier=tier,
        )

    # relevance کلمه‌ای (مثل ROMANO_KEYWORDS فعلی)
    if not _is_official(item) and not _is_trusted_outlet(item):
        kws = getattr(config, "ROMANO_KEYWORDS", []) or []
        if kws and not any(k.lower() in blob for k in kws):
            return NewsAnalysis(
                decision="reject", confidence=0.8, importance=1,
                category="irrelevant", relevance=False, quality="misleading",
                reason="no Liverpool keyword", tier=tier,
            )

    # اهمیت
    importance = 5
    if item.get("priority") or any(s in blob for s in _HIGH_SIGNALS):
        importance = 8
    if _is_official(item) and any(s in blob for s in ("statement", "announcement",
                                                      "signs", "signed",
                                                      "confirmed", "injury")):
        importance = 9

    # نوع محتوا
    category = "player_news"
    if any(s in blob for s in ("transfer", "here we go", "medical", "loan")):
        category = "transfer_rumour" if any(s in blob for s in SUSPICIOUS_SIGNALS) \
            else "transfer"
    elif "injury" in blob or "ruled out" in blob:
        category = "injury"
    elif "lineup" in blob or "team news" in blob:
        category = "lineup"
    elif any(s in blob for s in ("quote", "said", "told ")):
        category = "quote"
    elif any(s in blob for s in ("breaking", "exclusive", "confirmed")):
        category = "breaking"

    # تصمیم محافظه‌کارانه
    decision = "publish"
    needs_verify = False
    if category == "transfer_rumour" or any(s in blob for s in SUSPICIOUS_SIGNALS):
        decision = "review"
        needs_verify = True
    if importance >= config.AI_IMPORTANCE_HIGH and tier == "high":
        needs_verify = True
        decision = "review"

    return NewsAnalysis(
        decision=decision, confidence=0.6, importance=importance,
        category=category, relevance=True, quality="real",
        reason="deterministic fallback (AI unavailable)",
        needs_verification=needs_verify, tier=tier,
    )


class NewsEditor:
    def __init__(self, client=None):
        # import داخل تابع تا از حلقه import جلوگیری شود (client اختیاری)
        if client is None:
            from .hermes_client import HermesClient
            client = HermesClient()
        self.client = client

    def analyze(self, item: dict) -> NewsAnalysis:
        nid = news_id_of(item)
        tier = tier_of(item)
        trace(nid, "AI_TIER", tier=tier, source=item.get("source_tag"))

        # tier پایین + AI_ALWAYS_ANALYZE خاموش → سریع، ارزان، قطعی
        try:
            if tier == "low" and not config.AI_ALWAYS_ANALYZE:
                a = deterministic_analysis(item, tier=tier)
            else:
                a = self.client.analyze(item, tier=tier)
        except Exception as e:
            # دفاع عمقی: هر خطای AI → تحلیل قطعی (هرگز bot را down نمی‌کند)
            log.warning("AI analysis raised (%s) — deterministic fallback", e)
            a = deterministic_analysis(item, tier=tier)

        trace(nid, "AI_ANALYSIS", decision=a.decision,
              confidence=round(a.confidence, 2), importance=a.importance,
              category=a.category, quality=a.quality,
              needs_verification=a.needs_verification)
        return a

    def needs_verification(self, analysis: NewsAnalysis, item: dict) -> bool:
        if analysis.needs_verification:
            return True
        if analysis.decision == "review":
            return True
        # ادعاهای مهم از منابع غیررسمی همیشه بررسی می‌شوند
        if analysis.importance >= config.AI_IMPORTANCE_HIGH \
                and not (_is_official(item) or _is_trusted_outlet(item)):
            return True
        return False

    def verify(self, item: dict, analysis: NewsAnalysis) -> VerificationResult:
        """جمع‌آوری شواهد مستقل + ارزیابی AI + ذخیره در DB (مرحله ۵)."""
        nid = news_id_of(item)
        claim = (item.get("title") or "")[:200]
        trace(nid, "VERIFICATION", step="collecting-evidence")

        evidence = collect_evidence(item, claim)
        trace(nid, "VERIFICATION", evidence=len(evidence))

        result = self.client.verify(item, claim, evidence)
        result.claim = claim
        result.source = (item.get("source_tag") or item.get("source") or "")
        result.checked_at = time.time()
        # شواهدِ جمع‌آوری‌شده را همیشه حفظ کن، حتی اگر agent آن‌ها را در پاسخ
        # JSON بازتاب ندهد — رکورد DB باید هم شواهد را داشته باشد هم ارزیابی AI.
        if not result.evidence:
            result.evidence = list(evidence)

        # قانون ضد-هالوسینیشن: اگر شواهد کافی نیست، AI هرگز «تأیید» نمی‌کند
        if not evidence:
            result.verified = False
            result.confidence = min(result.confidence, 0.3)
            result.summary = ("هیچ شواهد مستقل‌ای پیدا نشد — خبر برای "
                              "بازبینی انسانی می‌ماند")
            trace(nid, "VERIFICATION", decision="human_review",
                  reason="no evidence")
        else:
            trace(nid, "VERIFICATION", verified=result.verified,
                  confidence=round(result.confidence, 2))

        try:
            db.record_verification(db.make_key(item), result.to_dict())
        except Exception as e:
            log.warning("could not persist verification: %s", e)
        return result


# ------------------------------------------------------------------ شواهد
_GOOGLE_NEWS = (
    "https://news.google.com/rss/search?q={q}+when:3d&hl=en-GB&gl=GB&ceid=GB:en"
)


def collect_evidence(item: dict, claim: str, max_items: int = 6) -> list:
    """جمع‌آوری شواهد مستقل (بدون کلید): جستجوی Google News + خبرهای مشابه
    در DB خودمان + خبرهای منبعِ دیگرِ همین سیکل.

    فقط URL/عنوان/خلاصه — هیچ‌وقت محتوای پولی/کامل.
    """
    evidence = []
    seen = set()

    def _add(src, title, url, snippet=""):
        if not url or url in seen:
            return
        seen.add(url)
        evidence.append({"source": src[:60], "title": (title or "")[:160],
                         "url": url, "snippet": (snippet or "")[:220]})

    # ۱) Google News RSS — کلمات کلیدی عنوان
    try:
        from sources.base import parse_rss, clean_text
        words = [w for w in re.findall(r"[A-Za-z]{4,}", claim)[:4] if w.lower()
                 not in ("liverpool", "lfc", "the", "and", "for", "with")]
        if not words:
            words = ["Liverpool", "FC"]
        q = "+".join(words[:4])
        for e in parse_rss(_GOOGLE_NEWS.format(q=q), timeout=15)[:max_items]:
            _add("Google News", e.get("title"), e.get("link"),
                 clean_text(e.get("summary") or ""))
    except Exception as e:
        log.debug("google news evidence failed: %s", e)

    # ۲) خبرهای مشابه در DB (منبع دیگر همان خبر را داده؟)
    try:
        for tag in db.similar_sources(item, hours=72):
            _add("DB: " + tag, f"same story reported by {tag}",
                 item.get("url") or "")
    except Exception as e:
        log.debug("db evidence failed: %s", e)

    return evidence[:max_items]
