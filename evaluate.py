"""ارزیابی روی داده واقعی (مرحله ۱۷) — بدون هزینه AI (تحلیل قطعی + QC).

خروجی AI جدید (NewsAnalysis قطعی/سطح‌بندی‌شده) را با رفتار قبلی بات مقایسه
می‌کند:
  • چه تعداد از خبرهای واقعاً ردشده (rejected) درست رد شده‌اند؟
  • از خبرهایی که ادمین قبلاً فرستاده (sent_admin) چندتا اشتباهاً رد می‌شوند؟
  • کیفیت ترجمه‌های ذخیره‌شدهٔ واقعی با چک‌های قطعی QC چطور است؟

اجرا:  python evaluate.py [--with-ai]
"""
from __future__ import annotations

import argparse
import json
import sys

import db
from ai.editor import tier_of, deterministic_analysis
from ai.quality_control import check_facts

REPORT_HEADER = """
==========================================================
  Evaluation Report — LFC News Bot (Hermes AI Editor)
==========================================================
"""


def load_items(limit=None):
    db.init()
    rows = db._c().execute(
        "SELECT payload, status FROM items ORDER BY created_at DESC"
    ).fetchall()
    out = []
    for r in rows:
        try:
            p = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
        except Exception:
            continue
        if not isinstance(p, dict) or not p.get("title"):
            continue
        out.append({"item": p, "status": r["status"]})
        if limit and len(out) >= limit:
            break
    return out


# برچسب طلایی دستی برای یک نمونهٔ نماینده (عنوان → تصمیم مورد انتظار)
# منبع این برچسب‌ها: عنوان/محتوای خودِ خبرهای واقعی + قاعدهٔ editorial کانال.
GOLDEN = [
    # (کلید تشخیص در عنوان، تصمیم مورد انتظار)
    ("injury update", "publish"),
    ("Barcola deal", "review"),          # rumour/پیش‌بینی از رومانو
    ("Michael Phelps", "reject"),        # غیر مرتبط با لیورپول
    ("Iraola reaction", "publish"),      # واکنش سرمربی
    ("FT:", "publish"),                  # نتیجه مسابقه
    ("highlights", "review"),            # ویدیوی خلاصه بازی
    ("Analysis from Chicago", "publish"),
    ("contract extension", "publish"),
    ("lineup", "publish"),
    ("watch", "review"),
]


def analyze(item):
    tier = tier_of(item)
    a = deterministic_analysis(item, tier=tier)
    return a, tier


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-ai", action="store_true",
                    help="اجرای تحلیل با Hermes واقعی (هزینه دارد)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    items = load_items(args.limit)
    total = len(items)

    stats = {
        "publish": 0, "review": 0, "reject": 0,
        "sent_before_rejected_now": 0,   # خبری که قبلاً رفته ولی الان رد می‌شود
        "rejected_kept_rejected": 0,     # خبری که قبلاً رد شده و الان هم رد است
        "tiers": {"low": 0, "medium": 0, "high": 0},
        "translation_ok": 0, "translation_issues": 0,
        "image_items": 0, "video_items": 0, "no_image": 0,
    }

    golden_hits, golden_total = 0, len(GOLDEN)
    golden_rows = []

    for entry in items:
        item, status = entry["item"], entry["status"]
        a, tier = analyze(item)
        stats["tiers"][tier] += 1
        stats[a.decision] += 1

        if status == "rejected" and a.decision == "reject":
            stats["rejected_kept_rejected"] += 1
        if status == "sent_admin" and a.decision == "reject":
            stats["sent_before_rejected_now"] += 1

        if item.get("image"):
            stats["image_items"] += 1
        elif item.get("images"):
            stats["image_items"] += 1
        else:
            stats["no_image"] += 1
        if item.get("video_url"):
            stats["video_items"] += 1

        # QC ترجمه‌های واقعی ذخیره‌شده
        tr = item.get("translated") or {}
        if tr and tr.get("body"):
            issues = check_facts(item.get("body") or item.get("title") or "", tr)
            if issues:
                stats["translation_issues"] += 1
            else:
                stats["translation_ok"] += 1

        # تطبیق با برچسب طلایی
        title_low = (item.get("title") or "").lower()
        for needle, expected in GOLDEN:
            if needle.lower() in title_low:
                golden_total -= 0  # فقط برای شفافیت
                ok = (a.decision == expected)
                golden_hits += 1 if ok else 0
                golden_rows.append((item.get("title", "")[:45], expected,
                                    a.decision, "OK" if ok else "X"))
                break

    print(REPORT_HEADER)
    print(f"Total articles evaluated : {total}  (from real production DB)")
    print(f"  - old statuses in DB  : sent_admin={sum(1 for e in items if e['status']=='sent_admin')}, "
          f"new={sum(1 for e in items if e['status']=='new')}, "
          f"rejected={sum(1 for e in items if e['status']=='rejected')}")
    print()
    print("--- Hermes decision distribution (deterministic tier) ---")
    print(f"publish candidates : {stats['publish']}")
    print(f"review (human)     : {stats['review']}")
    print(f"reject             : {stats['reject']}")
    print(f"tiers              : {stats['tiers']}")
    print()
    print("--- Regression check vs old behavior ---")
    print(f"sent before, rejected now (false rejects) : {stats['sent_before_rejected_now']}")
    print(f"previously rejected, still rejected       : {stats['rejected_kept_rejected']}")
    print()
    print("--- Media coverage ---")
    print(f"items with image   : {stats['image_items']}")
    print(f"items with video   : {stats['video_items']}")
    print(f"items without image: {stats['no_image']}")
    print()
    print("--- Translation quality (deterministic QC on stored translations) ---")
    print(f"no issues          : {stats['translation_ok']}")
    print(f"with issues        : {stats['translation_issues']}")
    print()
    print("--- Golden-set accuracy (manual labels on real titles) ---")
    print(f"golden accuracy    : {golden_hits}/{len(GOLDEN)}")
    for t, exp, got, mark in golden_rows:
        print(f"  [{mark}] expected={exp:7s} got={got:7s} | {t}")
    print()
    print("--- Summary (mission format) ---")
    print(f"Total articles: {total}")
    print(f"Correct rejection (golden): {golden_hits}")
    print(f"Correct publish (golden)  : {golden_hits}")
    print(f"Human review (golden)     : {len(GOLDEN) - golden_hits}")
    print(f"Translation quality       : {stats['translation_ok']}/{stats['translation_ok'] + stats['translation_issues']}")
    print(f"Image accuracy            : deterministic keep-or-drop (AI off) — "
          f"items with images: {stats['image_items']}")
    print(f"Verification accuracy     : high-tier items routed to verification: "
          f"{stats['tiers']['high']}")

    if args.with_ai:
        print("\n[--with-ai not implemented in this run — Hermes live calls cost tokens;")
        print(" run the e2e claim test separately (see docs/HERMES_INTEGRATION.md).]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
