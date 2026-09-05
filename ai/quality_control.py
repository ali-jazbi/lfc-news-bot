"""کنترل کیفیت ترجمه (مرحله ۶).

دو لایه:
  1. چک‌های قطعی (بدون AI): نام‌ها، اعداد، تاریخ‌ها، نقل‌قول‌ها و طول متن —
     هر عدد/نامِ مهمِ متن اصلی باید در ترجمه باشد (با نرمال‌سازی ارقام فارسی).
  2. بازبینی AI با نمونه‌های واقعی کانال — اگر کیفیت پایین بود → اصلاح
     (حداکثر HERMES_MAX_REVISIONS بار) و بعد → human_review.

نکته مهم: سیستم ترجمه فعلی (translate.py) حذف نشده؛ این ماژول روی خروجیِ
همان زنجیره QC اضافه می‌کند.
"""
from __future__ import annotations

import logging
import re

import config

from .schemas import TranslationReview
from .tracing import trace, news_id_of

log = logging.getLogger("ai.qc")

# تبدیل ارقام فارسی/عربی به لاتین برای مقایسه اعداد
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _norm_digits(t: str) -> str:
    return (t or "").translate(_FA_DIGITS)


def _numbers(text: str):
    return set(re.findall(r"\d{2,}", _norm_digits(text or "")))


def _names(text: str, glossary) -> set:
    """نام‌های شناخته‌شده (glossary) که در متن آمده — برای چک omission."""
    low = (text or "").lower()
    found = set()
    for en in glossary:
        if len(en.split()) >= 2 and en.lower() in low:
            found.add(en.lower())
    return found


def _missing_names(src: str, tr_text: str, glossary) -> list:
    """نامِ دوکلمه‌ای که در متن اصلی هست ولی معادل فارسی‌اش در ترجمه نیست.
    معادل فارسی از VALUE خودِ glossary خوانده می‌شود (نه کلید )."""
    low_src = (src or "").lower()
    tr_blob = tr_text or ""
    missing = []
    for en, fa in glossary.items():
        if len(en.split()) >= 2 and en.lower() in low_src:
            if not fa or fa not in tr_blob:
                missing.append(en)
    return missing


def check_facts(source_text: str, tr: dict, glossary=None) -> list:
    """چک‌های قطعی — خروجی: لیست مشکلات [str]. خالی = مشکلی نیست."""
    glossary = glossary or getattr(config, "GLOSSARY", {})
    issues = []
    src = source_text or ""
    tr_title = tr.get("title") or ""
    tr_body = tr.get("body") or ""
    tr_blob = tr_title + " " + tr_body

    # ۱) اعداد بزرگ (≥۲ رقم) که در متن اصلی هست ولی در ترجمه نیست
    src_nums = _numbers(src)
    tr_nums = _numbers(tr_blob)
    missing = sorted(n for n in src_nums if n not in tr_nums and n not in
                     ("20", "21", "22", "23", "24", "25", "26", "27", "28",
                      "29", "30", "10", "11", "12", "13", "14", "15", "16",
                      "17", "18", "19"))
    # اعداد ۱۰-۳۰ می‌توانند سن/سال باشند؛ فقط اگر «تبدیل‌شده» بودند نادیده بگیر.
    # برای سادگی: اعداد ≥ ۳۱ یا الگوهای پولی/تاریخ حتماً باید بمانند
    missing = [n for n in missing if int(n) >= 31]
    if missing:
        issues.append(f"missing numbers: {', '.join(missing[:5])}")

    # ۲) نام‌های دوکلمه‌ای (بازیکن/مربی/تیم) که معادل فارسی‌شان در ترجمه نیست
    missed = _missing_names(src, tr_blob, glossary)
    if missed:
        issues.append("missing names: " + ", ".join(missed[:5]))

    # ۲-ب) نام‌های دوکلمه‌ایِ مهمِ متن اصلی باید در عنوان ترجمه هم باشند
    #     وقتی خبر درباره همان شخص است (نه فقط بدنه).
    #     ملایم: اگر تکهٔ آخر نام (نام خانوادگی) در عنوان هست، قبول است
    #     (عنوان خبری می‌تواند فقط «صلاح» داشته باشد نه «محمد صلاح»).
    #     (اعدادِ عنوان جدا چک نمی‌شوند چون source_text می‌تواند فقط body
    #      باشد؛ اعداد مهم در چک ۱ همه‌جا بررسی می‌شوند.)
    src_first = (src or "")[:200]
    if len(tr_title.strip()) >= 8:
        missing_in_title = []
        for en in glossary:
            if len(en.split()) >= 2 and en.lower() in src_first.lower():
                fa = glossary.get(en) or ""
                surname = (en.split()[-1] if en.split() else "")
                if not fa:
                    continue
                # معادل فارسی در عنوان هست؟ یا نام خانوادگیِ فارسی در عنوان؟
                if fa in tr_title:
                    continue
                fa_surname = (fa.split()[-1] if fa.split() else "")
                if len(fa_surname) >= 3 and fa_surname in tr_title:
                    continue
                missing_in_title.append(en)
        if missing_in_title:
            issues.append("title missing names: " + ", ".join(missing_in_title[:3]))

    # ۳) طول متن — کمتر از ۳۰۰ کاراکتر یعنی ناقص
    if len(tr_body.strip()) < 300:
        issues.append("body too short (likely incomplete)")

    # ۳-ب) عنوان خیلی بلند/خالی
    if not tr_title.strip():
        issues.append("title empty")
    elif len(tr_title) > 200:
        issues.append("title too long")

    # ۴) متن لاتینِ باقی‌مانده (به‌جز نام‌های خاص مجاز)
    latin = re.findall(r"[A-Za-z]{4,}", tr_body)
    allowed = {"https", "www", "telegram", "feb", "jan", "mar", "apr", "jun",
               "jul", "aug", "sep", "oct", "nov", "dec"}
    leftover = [w for w in latin if w.lower() not in allowed]
    if leftover:
        issues.append("latin words left: " + ", ".join(leftover[:5]))

    return issues


def style_examples(limit=None):
    """نمونه‌های واقعی پست‌های approved/published — فقط برای استایل."""
    try:
        import db
        return db.channel_examples(limit or 4)
    except Exception as e:
        log.debug("no channel examples: %s", e)
        return []


def translate_with_qc(item: dict, editor=None, tr=None):
    """ترجمه + QC — خروجی: (tr, review, human_review_needed).

    tr خودِ خروجی translate.translate است (زنجیره موجود)؛ این تابع فقط
    QC/اصلاح را اضافه می‌کند. اگر AI خاموش باشد، فقط چک‌های قطعی.
    """
    import translate
    nid = news_id_of(item)

    if tr is None:
        trace(nid, "TRANSLATION", stage="start")
        tr = translate.translate(item)
        if not tr:
            return None, None, True
        trace(nid, "TRANSLATION", provider=tr.get("provider"),
              machine=tr.get("machine", False))

    if not config.HERMES_ENABLED:
        issues = check_facts(item.get("body") or item.get("title") or "", tr)
        if issues:
            trace(nid, "TRANSLATION_QC", ok=False, issues=" | ".join(issues[:3]))
        else:
            trace(nid, "TRANSLATION_QC", ok=True)
        return tr, TranslationReview(ok=not issues, score=0.7 if issues else 0.9,
                                     issues=issues), bool(issues)

    # بازبینی AI با نمونه‌های کانال
    examples = style_examples()
    try:
        review = editor.client.review_translation(item, tr, examples)
    except Exception as e:
        log.warning("AI translation QC crashed (%s) — fail-closed", e)
        review = TranslationReview.unavailable(f"AI QC crashed: {e}")
    trace(nid, "TRANSLATION_QC", ok=review.ok, score=round(review.score, 2),
          available=review.available, issues=len(review.issues))

    # fail-closed: اگر AI QC اصلاً اجرا نشد → بدون تغییر وضعیت، human review
    if not review.available:
        return tr, review, True

    # اصلاح تا سقف (MAX_REVISIONS) — جلوگیری از loop بی‌نهایت
    revised = tr
    for attempt in range(config.HERMES_MAX_REVISIONS):
        if review.ok or not (review.revision_title or review.revision_body):
            break
        trace(nid, "TRANSLATION_REVISE", attempt=attempt + 1)
        revised = _apply_revision(revised, review)
        try:
            review = editor.client.review_translation(item, revised, examples)
        except Exception as e:
            log.warning("AI translation QC crashed on revise (%s) — fail-closed", e)
            review = TranslationReview.unavailable(f"AI QC crashed: {e}")
            return revised, review, True
        trace(nid, "TRANSLATION_REVIEW", ok=review.ok,
              score=round(review.score, 2), attempt=attempt + 1)

    # چک‌های قطعی روی نسخه نهایی
    issues = check_facts(item.get("body") or item.get("title") or "", revised)
    if issues and review.ok:
        review.ok = False
        review.issues = list(review.issues) + issues
        review.human_review_required = True
        trace(nid, "TRANSLATION_QC", ok=False, deterministic=issues[:3])

    # بعد از سقف اصلاح (یا بدون متن اصلاح) و هنوز بد → human_review
    human_review = review.human_review_required or not review.ok
    return revised, review, human_review


def _apply_revision(tr: dict, review: TranslationReview) -> dict:
    """نسخه اصلاح‌شده — عنوان و بدنه را مستقل اصلاح می‌کند: اگر AI فقط
    یکی را داده باشد، دیگری دست نمی‌خورد."""
    out = dict(tr)
    changed = False
    if review.revision_title and review.revision_title.strip():
        out["title"] = review.revision_title.strip()[:120]
        changed = True
    if review.revision_body and review.revision_body.strip():
        out["body"] = review.revision_body.strip()
        changed = True
    if changed:
        out["revised"] = True
    return out
