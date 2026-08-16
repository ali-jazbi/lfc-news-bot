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

# نشانه‌های opinion — هرگز به‌عنوان خبر منتشر نمی‌شود.
# نکته: «i think/in my view» در بدنهٔ خبرنگاران نقل‌وانتقال رایج است و خودش
# opinion نیست؛ فقط ساختارهای صریح opinion (عنوان/شروع‌کنندهٔ بحث) رد می‌شوند.
_OPINION_TITLE_SIGNALS = (
    "why liverpool should", "why i think", "should liverpool sell",
    "should sell salah", "should the club", "my honest opinion",
    "an opinion:", "opinion:", "column:",
)
_OPINION_BODY_SIGNALS = (
    "in my opinion,", "this is my opinion", "my controversial take",
    "in this opinion piece", "this article is my opinion",
    "i'm going to argue", "i will argue",
)

# نشانه‌های clickbait — نویز
_CLICKBAIT_SIGNALS = (
    "you won't believe", "you wont believe", "incredible transformation",
    "shocking", "mind blowing", "mind-blowing", "click here", "gallery inside",
    "what happened next", "you need to see", "will shock",
)

# سال‌های گذشته در متن = خبر قدیمی
import datetime as _dt
_CURRENT_YEAR = _dt.date.today().year


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


# نهادهای لیورپولی از glossary — فقط این‌ها relevance می‌سازند (نه حریف‌ها)
_LFC_GLOSSARY_KEYS = (
    "liverpool", "anfield", "kirkby", "axa training centre", "arne slot",
    "mohamed salah", "virgil van dijk", "alisson", "ryan gravenberch",
    "dominik szoboszlai", "alexis mac allister", "curtis jones",
    "conor bradley", "ibrahima konate", "kop end", "kop", "reds",
    "merseyside derby", "andoni iraola", "iraola", "slot", "axa",
    "premier league", "champions league", "carabao cup", "fa cup",
)


def _is_liverpool_relevant(blob: str, item: dict) -> bool:
    """آیا متن درباره لیورپول است؟ کلمات کلیدی + نهادهای لیورپولی."""
    kws = getattr(config, "ROMANO_KEYWORDS", []) or []
    if any(k.lower() in blob for k in kws):
        return True
    # فقط نهادهای لیورپولی از glossary (بازیکن/مربی/باشگاه) — حریف‌ها نه
    try:
        for en in getattr(config, "GLOSSARY", {}) or {}:
            if en.lower() not in _LFC_GLOSSARY_KEYS:
                continue
            if en.lower() in blob:
                return True
    except Exception:
        pass
    # نام‌های شناخته‌شده تک‌کلمه‌ای که در glossary نیستند
    for name in ("alexander-arnold", "trent", "nunez", "gakpo", "diaz",
                 "jota", "kelleher", "quansah", "endo", "chiesa", "klopp",
                 "zubimendi", "huijsen", "kerkez"):
        if name in blob:
            return True
    return False


def _is_outdated(item: dict) -> bool:
    """سال گذشته در «عنوان» = خبر قدیمی.

    عمداً فقط عنوان بررسی می‌شود: سال در بدنه معمولاً پیشینه/مقایسه است
    (مثل «joined in 2021» یا «2025-26 season») و قدیمی بودن خبر را نشان
    نمی‌دهد. الگوی فصل «2025-26» هم حذف می‌شود.
    """
    blob = (item.get("title") or "").lower()
    clean = re.sub(r"20\d{2}\s*[-/]\s*\d{2}", " ", blob)
    for m in re.findall(r"\b(19\d{2}|20\d{2})\b", clean):
        y = int(m)
        if y > 1900 and _CURRENT_YEAR - y >= 1:
            return True
    return False


def deterministic_analysis(item: dict, tier: str = "medium") -> NewsAnalysis:
    """Fallback قطعی — همان منطق کلمه‌ای فعلی بات، اما در قالب NewsAnalysis.

    بدون هیچ هزینه AI؛ فقط برای وقتی Hermes/LLM در دسترس نیست یا خراب است.
    محافظه‌کار است: هر ابهامی → review (انسان تصمیم می‌گیرد).
    """
    blob = _blob(item)
    title = (item.get("title") or "").lower()

    # قواعد قطعی کانال — همان hard rules (reject بدون ابهام)
    hard = _hard_rules_analysis(item, tier=tier)
    if hard is not None:
        return hard

    # relevance — برای همه منابع (حتی معتبر: BBC/Sky هم خبر غیر-لیورپول می‌دهند)
    if not _is_official(item) and not _is_liverpool_relevant(blob, item):
        return NewsAnalysis(
            decision="reject", confidence=0.8, importance=1,
            category="irrelevant", relevance=False, quality="misleading",
            reason="no Liverpool relevance", tier=tier,
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
    _TRANSFER_WORDS = ("transfer", "here we go", "medical", "loan", "asking price",
                       "personal terms", "buy-out", "release clause", "fee",
                       "move to", "interest in", "wants to join", "keen on")
    if any(s in blob for s in _TRANSFER_WORDS):
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

    # «reports/according to reports/claims» داخل محتوا = محتوای rumour،
    # حتی اگر منبع رسمی باشگاه باشد (باشگاه هم گاهی بازتاب گزارش رسانه‌هاست)
    if any(s in blob for s in ("according to reports", "according to multiple reports",
                               "reports claim", "reports suggest", "per reports",
                               "sources say", "sources claim", "reportedly")):
        category = "transfer_rumour" if any(s in blob for s in _TRANSFER_WORDS) \
            else category

    # تصمیم محافظه‌کارانه — سیاست دقیق (مرحله ۱۳):
    #   reject فقط وقتی قطعاً بی‌ربط/ممنوع/نویز است
    #   review وقتی ابهام/rumour/اعتماد کم/ادعای مهم است
    #   publish فقط وقتی مرتبط + کیفیت قابل قبول + اعتماد مناسب است
    decision = "publish"
    needs_verify = False
    if category == "transfer_rumour" or any(s in blob for s in SUSPICIOUS_SIGNALS):
        decision = "review"
        needs_verify = True
    # انتقال تأییدشده (complete/here we go/confirmed/signed) از منبع معتبر
    # → publish حتی با اهمیت بالا (تأییدشده است، نه rumour)
    _CONFIRMED = ("here we go", "complete", "completed", "confirmed", "has signed",
                  "has completed", "signs", "signed a")
    confirmed_transfer = category in ("transfer", "breaking") and any(
        s in blob for s in _CONFIRMED)

    # ادعای مهم از هر منبع غیررسمی (حتی BBC/Sky) → verification اجباری (مرحله ۱۴)
    # استثنا: انتقال تأییدشده از منبع معتبر
    if importance >= config.AI_IMPORTANCE_HIGH and not _is_official(item) \
            and not (confirmed_transfer and _is_trusted_outlet(item)):
        needs_verify = True
        decision = "review"
    if importance >= config.AI_IMPORTANCE_HIGH and tier == "high":
        needs_verify = True
        decision = "review"
    # محتوای rumour از منبع رسمی هم (بازتاب گزارش رسانه) → review
    if category == "transfer_rumour" and _is_official(item):
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
        src_health = _source_health_of(item)
        trace(nid, "AI_TIER", tier=tier, source=item.get("source_tag"),
              source_health=src_health)

        # قواعد قطعی کانال همیشه اول اجرا می‌شوند — Hermes هرگز نمی‌تواند
        # خبر women's team، SKIP_KEYWORDS یا خبر قدیمی را publish کند، حتی اگر
        # LLM آن را «مرتبط و جالب» بداند (Hermes قواعد کانال را نمی‌داند).
        hard = _hard_rules_analysis(item, tier=tier)
        if hard is not None:
            trace(nid, "AI_ANALYSIS", decision=hard.decision,
                  confidence=round(hard.confidence, 2), importance=hard.importance,
                  category=hard.category, quality=hard.quality,
                  needs_verification=hard.needs_verification,
                  source="hard-rule")
            return hard

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

        # safety net: قواعد قطعی باز هم روی خروجی AI اعمال می‌شود
        # (اگر LLM به‌هرحال چیزی publish کرد که قطعاً ممنوع است)
        hard = _hard_rules_analysis(item, tier=tier)
        if hard is not None and hard.decision == "reject":
            a = hard
        else:
            a = _policy_guard(item, a)

        # سلامت منبع (مرحله ۱۵): منبع degraded/failed → اعتماد کمتر، review
        if src_health in ("degraded", "failed"):
            a.confidence = max(0.0, a.confidence - 0.2)
            if a.decision == "publish" and a.confidence < 0.6:
                a.decision = "review"
                a.needs_verification = True
                a.reason = ((a.reason or "") + f" | source health={src_health}")
            trace(nid, "AI_SOURCE_HEALTH", status=src_health,
                  confidence=round(a.confidence, 2))

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
        # ادعاهای مهم از منابع غیررسمی همیشه بررسی می‌شوند (مرحله ۱۴)
        if analysis.importance >= config.AI_IMPORTANCE_HIGH \
                and not (_is_official(item) or _is_trusted_outlet(item)):
            return True
        # منبع degraded + خبر مهم → بررسی
        if _source_health_of(item) in ("degraded", "failed") \
                and analysis.importance >= 6:
            return True
        return False

    def analyze_many(self, items: list, skip_verify=True):
        """تحلیل دسته‌ای (برای evaluation) — بدون verification مگر لازم باشد."""
        out = []
        for item in items:
            try:
                a = self.analyze(item)
                out.append(a)
            except Exception as e:
                log.warning("batch analyze failed for %s: %s",
                            (item.get("title") or "")[:40], e)
                out.append(deterministic_analysis(item, tier=tier_of(item)))
        return out

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

    # ۲) خبرهای مشابه در DB (منبع دیگر همان خبر را داده؟) — با tier منبع
    try:
        for tag in db.similar_sources(item, hours=72):
            from .hermes_client import _tier_of_source
            tier = _tier_of_source("", tag)
            _add(f"DB: {tag} (Tier {tier})", f"same story reported by {tag}",
                 item.get("url") or "")
    except Exception as e:
        log.debug("db evidence failed: %s", e)

    # ۳) شواهد را با tier غنی کن (URL → tier) برای وزن‌دهی در verification
    from .hermes_client import _tier_of_source
    for e in evidence:
        e["tier"] = _tier_of_source(e.get("url", ""), e.get("source", ""))
    evidence.sort(key=lambda e: e.get("tier", 5))
    return evidence[:max_items]


def _source_health_of(item: dict) -> str:
    """وضعیت سلامت منبع برای دخالت در تصمیم editorial (مرحله ۱۵)."""
    try:
        src = (item.get("source_tag") or item.get("source") or "").strip()
        if not src:
            return "healthy"
        info = db.source_health_status(src)
        return info.get("status") or "healthy"
    except Exception:
        return "healthy"


def _policy_guard(item: dict, a: "NewsAnalysis") -> "NewsAnalysis":
    """قواعد سیاست editorial روی خروجی AI (مرحله ۱۳/۱۴).

    وقتی LLM چیزی publish کرد که سیاست کانال اجازه نمی‌دهد، downgrade می‌شود:
      • ادعای مهم (importance>=7) از منبع غیررسمی → review + verification
        (مگر انتقال تأییدشده از منبع معتبر)
      • source health ضعیف → اعتماد کمتر
    این‌ها قواعد قطعی‌اند، نه سلیقه LLM.
    """
    blob = _blob(item)
    if a.decision != "publish":
        return a
    confirmed = any(s in blob for s in
                    ("here we go", "complete", "completed", "confirmed",
                     "has signed", "has completed", "signs", "signed a"))
    # فقط categoryهای حساس guard می‌شوند — «Manager of the Month» از BBC یا
    # «match report» از Guardian خبرهای قطعی‌اند و نباید review شوند.
    sensitive = a.category in ("transfer", "transfer_rumour", "injury", "breaking")
    non_official = not _is_official(item)
    # injury/breaking حتی با importance 7 از منبع غیررسمی → verification
    if a.category in ("injury", "breaking") and a.importance >= 7 \
            and non_official and not confirmed:
        a.decision = "review"
        a.needs_verification = True
        a.reason = ((a.reason or "") + " | policy: injury/breaking from "
                    "non-official source requires verification")
    # transfer/transfer_rumour فقط وقتی مهم است (>=8)
    elif a.category in ("transfer", "transfer_rumour") and a.importance >= 8 \
            and non_official and not (confirmed and _is_trusted_outlet(item)):
        a.decision = "review"
        a.needs_verification = True
        a.reason = ((a.reason or "") + " | policy: major transfer from "
                    "non-official source requires verification")
    src_health = _source_health_of(item)
    if src_health in ("degraded", "failed") and a.decision == "publish":
        a.confidence = max(0.0, a.confidence - 0.2)
        if a.confidence < 0.6:
            a.decision = "review"
            a.needs_verification = True
    return a


def _hard_rules_analysis(item: dict, tier: str = "medium") -> "NewsAnalysis | None":
    """قواعد قطعی کانال — همیشه اعمال می‌شوند (حتی وقتی Hermes روشن است).

    Hermes قواعد کانال را نمی‌داند (SKIP_KEYWORDS، INCLUDE_WOMEN، خبر قدیمی،
    opinion/clickbait). این‌ها ruleهای editorial قطعی‌اند و هیچ LLM نباید
    بتواند آن‌ها را override کند. خروجی None یعنی قانونی رد نشد.
    """
    blob = _blob(item)
    title = (item.get("title") or "").lower()

    for kw in getattr(config, "SKIP_KEYWORDS", []):
        if kw and kw.lower() in title:
            return NewsAnalysis(
                decision="reject", confidence=0.97, importance=1,
                category="irrelevant", relevance=False, quality="clickbait",
                reason=f"skip keyword: {kw} (hard rule)", tier=tier,
            )
    if not config.INCLUDE_WOMEN and re.search(r"women|wsl", blob):
        return NewsAnalysis(
            decision="reject", confidence=0.95, importance=1,
            category="irrelevant", relevance=False, quality="outdated",
            reason="women's team not covered (hard rule)", tier=tier,
        )
    if _is_outdated(item):
        return NewsAnalysis(
            decision="reject", confidence=0.9, importance=1,
            category="irrelevant", relevance=False, quality="outdated",
            reason="old news (past year in title, hard rule)", tier=tier,
        )
    if any(s in title for s in _OPINION_TITLE_SIGNALS) \
            or any(s in blob for s in _OPINION_BODY_SIGNALS):
        return NewsAnalysis(
            decision="reject", confidence=0.85, importance=1,
            category="opinion", relevance=True, quality="opinion",
            reason="opinion piece (hard rule)", tier=tier,
        )
    if any(s in blob for s in _CLICKBAIT_SIGNALS):
        return NewsAnalysis(
            decision="reject", confidence=0.9, importance=1,
            category="irrelevant", relevance=False, quality="clickbait",
            reason="clickbait (hard rule)", tier=tier,
        )
    return None
