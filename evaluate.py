"""ارزیابی واقعی سردبیر Hermes روی داده واقعی (مرحله ۱۷/۲۲/۲۳).

دو حالت:
  python evaluate.py            → بدون هزینه AI (تحلیل قطعی + golden)
  python evaluate.py --with-ai  → با Hermes واقعی (هزینه دارد؛ نتیجه cache می‌شود)

ویژگی‌ها:
  • dataset = آیتم‌های واقعی DB + golden set (evaluation/golden.json)
  • هر item یک رکورد مستقل (JSON) + خروجی Markdown
  • confusion matrix واقعی (Expected x Actual) — نه متریک‌های تکراری/جعلی
  • cache نتیجه Hermes تا اجرای مجدد دوباره هزینه نداشته باشد
  • هرگز DB production را mutate نمی‌کند (فقط خواندن)
  • هزینه AI (تعداد agent/LLM/verification/QC calls + latency) log می‌شود

خروجی: evaluation/results/evaluation_<mode>_<ts>.{json,md}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import config
import db

REPORT_HEADER = """
==========================================================
  Evaluation Report - LFC News Bot (Hermes AI Editor)
==========================================================
"""

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "evaluation", "results")


# ------------------------------------------------------------------ data
def load_items(limit=None):
    """آیتم‌های واقعی DB — فقط خواندن، هیچ تغییری نه."""
    db.init()
    rows = db._c().execute(
        "SELECT key, payload, status, analysis, verification FROM items "
        "ORDER BY created_at DESC"
    ).fetchall()
    out = []
    for r in rows:
        try:
            p = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
        except Exception:
            continue
        if not isinstance(p, dict) or not p.get("title"):
            continue
        rec = {"key": r["key"], "item": p, "old_status": r["status"],
               "stored_analysis": json.loads(r["analysis"])
               if r["analysis"] else None,
               "stored_verification": json.loads(r["verification"])
               if r["verification"] else None}
        out.append(rec)
        if limit and len(out) >= limit:
            break
    return out


def load_golden():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "evaluation", "golden.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("entries") or []
    except Exception as e:
        print(f"[warn] golden.json not loaded: {e}")
        return []


def _decision_of(analysis: dict) -> str:
    return (analysis or {}).get("decision", "review")


def _match_golden(title: str, golden_entries: list):
    """اولین golden entry که match_title داخل عنوان واقعی باشد."""
    title_low = (title or "").lower()
    for g in golden_entries:
        mt = (g.get("match_title") or "").lower()
        if mt and mt in title_low:
            return g
    return None


# ------------------------------------------------------------------ AI cache
def _cache_path(mode):
    return os.path.join(CACHE_DIR, f"ai_cache_{mode}.json")


def _load_cache(mode):
    try:
        with open(_cache_path(mode), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(mode, cache):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(mode), "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ metrics
class CostTracker:
    def __init__(self):
        self.agent_calls = 0
        self.llm_calls = 0
        self.verification_calls = 0
        self.qc_calls = 0
        self.errors = 0
        self.latency_ms = 0.0

    def to_dict(self):
        return {
            "agent_calls": self.agent_calls,
            "llm_calls": self.llm_calls,
            "verification_calls": self.verification_calls,
            "translation_qc_calls": self.qc_calls,
            "errors": self.errors,
            "total_latency_ms": round(self.latency_ms, 1),
        }


# ------------------------------------------------------------------ analysis
def deterministic_for(item: dict):
    from ai.editor import tier_of, deterministic_analysis
    tier = tier_of(item)
    a = deterministic_analysis(item, tier=tier)
    return a, tier


def hermes_analyze(item: dict, cache: dict, cost: CostTracker, key: str,
                   with_verify: bool):
    """تحلیل Hermes واقعی با cache. خروجی: (analysis_dict, verification_dict|None)."""
    cached = cache.get(key)
    if cached is not None:
        return cached.get("analysis"), cached.get("verification")

    from ai.editor import NewsEditor
    editor = NewsEditor()
    t0 = time.time()
    try:
        a = editor.analyze(item)
        cost.llm_calls += 1
        a_dict = a.to_dict()
    except Exception as e:
        cost.errors += 1
        a_dict = {"decision": "review", "confidence": 0.0, "importance": 5,
                  "category": "player_news", "quality": "real",
                  "reason": f"AI crash: {e}", "needs_verification": False,
                  "tier": "medium"}

    v_dict = None
    if with_verify and a_dict.get("needs_verification"):
        try:
            vr = editor.verify(item, a)
            v_dict = vr.to_dict()
            cost.verification_calls += 1
        except Exception as e:
            cost.errors += 1
            v_dict = {"verified": False, "confidence": 0.0,
                      "summary": f"verification crash: {e}"}

    cost.latency_ms += (time.time() - t0) * 1000
    cache[key] = {"analysis": a_dict, "verification": v_dict}
    return a_dict, v_dict


# ------------------------------------------------------------------ golden run
def golden_confusion(records):
    """confusion matrix واقعی Expected x Actual روی golden items."""
    labels = ("publish", "review", "reject")
    matrix = {e: {a: 0 for a in labels} for e in labels}
    for r in records:
        if r.get("golden") is None:
            continue
        exp = r["golden"].get("expected_decision", "review")
        act = r["actual_decision"]
        if exp in matrix and act in matrix[exp]:
            matrix[exp][act] += 1
    return matrix


def _precision(matrix, expected_class, actual_class):
    """از منظر human label: دقت طبقهٔ actual وقتی expected=expected_class است."""
    col = sum(matrix[e][actual_class] for e in matrix)
    if not col:
        return 0.0
    return matrix[expected_class][actual_class] / col


def _rate(matrix, expected_class, actual_classes):
    total = sum(matrix[expected_class].values())
    if not total:
        return 0.0
    hit = sum(matrix[expected_class][c] for c in actual_classes)
    return hit / total


def compute_metrics(records, stats):
    matrix = golden_confusion(records)
    golden = [r for r in records if r.get("golden") is not None]
    golden_total = len(golden)
    correct = sum(1 for r in golden
                  if r["golden"]["expected_decision"] == r["actual_decision"])

    old_sent = [r for r in records if r["old_status"] == "sent_admin"]
    old_rej = [r for r in records if r["old_status"] == "rejected"]

    # از منظر golden: publishِ درست یعنی expected=publish و actual=publish
    publish_precision = _precision(matrix, "publish", "publish")
    reject_precision = _precision(matrix, "reject", "reject")
    # false reject: golden می‌گوید publish ولی ما reject کردیم
    false_reject_rate = _rate(matrix, "publish", ("reject",))
    # false accept risk: golden می‌گوید reject ولی ما publish کردیم
    false_accept_risk = _rate(matrix, "reject", ("publish",))
    review_rate = (stats["review"] / stats["total"]) if stats["total"] else 0.0

    return {
        "matrix": matrix,
        "golden_total": golden_total,
        "golden_correct": correct,
        "golden_accuracy": (correct / golden_total) if golden_total else 0.0,
        "publish_precision": round(publish_precision, 3),
        "reject_precision": round(reject_precision, 3),
        "false_reject_rate": round(false_reject_rate, 3),
        "false_accept_risk": round(false_accept_risk, 3),
        "review_rate": round(review_rate, 3),
        "old_sent_now_rejected": len([r for r in old_sent
                                      if r["actual_decision"] == "reject"]),
        "old_rejected_now_publish": len([r for r in old_rej
                                         if r["actual_decision"] == "publish"]),
        "old_rejected_now_review": len([r for r in old_rej
                                        if r["actual_decision"] == "review"]),
        "old_sent_total": len(old_sent),
        "old_rejected_total": len(old_rej),
    }


# ------------------------------------------------------------------ report
def build_report(records, stats, metrics, cost, mode, golden_entries):
    lines = [REPORT_HEADER]
    lines.append(f"Mode               : {mode}")
    lines.append(f"Total articles     : {stats['total']} "
                 f"(DB={stats['db_total']}, golden-only={stats['golden_only']})")
    lines.append(f"Golden items       : {metrics['golden_total']}")
    lines.append(f"AI cost            : {json.dumps(cost.to_dict())}")
    lines.append("")
    lines.append("--- Decision distribution (actual) ---")
    lines.append(f"publish candidates : {stats['publish']}")
    lines.append(f"review (human)     : {stats['review']}")
    lines.append(f"reject             : {stats['reject']}")
    lines.append(f"tiers              : {stats['tiers']}")
    lines.append("")
    lines.append("--- Regression vs old behavior ---")
    lines.append(f"old sent, now rejected      : {metrics['old_sent_now_rejected']} "
                 f"of {metrics['old_sent_total']}")
    lines.append(f"old rejected, now publish   : {metrics['old_rejected_now_publish']} "
                 f"of {metrics['old_rejected_total']}")
    lines.append(f"old rejected, now review    : {metrics['old_rejected_now_review']} "
                 f"of {metrics['old_rejected_total']}")
    lines.append("")
    lines.append("--- Golden metrics (real confusion matrix) ---")
    labels = ("publish", "review", "reject")
    m = metrics["matrix"]
    lines.append("Expected \\ Actual" + "".join(f"{l:>10}" for l in labels))
    for e in labels:
        lines.append(f"{e:>16}" + "".join(f"{m[e][a]:>10}" for a in labels))
    lines.append(f"golden_accuracy     : {metrics['golden_correct']}/"
                 f"{metrics['golden_total']} = {metrics['golden_accuracy']:.3f}")
    lines.append(f"publish_precision   : {metrics['publish_precision']}")
    lines.append(f"reject_precision    : {metrics['reject_precision']}")
    lines.append(f"false_reject_rate   : {metrics['false_reject_rate']} "
                 f"(golden publish, we rejected)")
    lines.append(f"false_accept_risk   : {metrics['false_accept_risk']} "
                 f"(golden reject, we published)")
    lines.append(f"review_rate         : {metrics['review_rate']}")
    lines.append("")
    lines.append("--- Media coverage ---")
    lines.append(f"items with image    : {stats['image_items']}")
    lines.append(f"items with video    : {stats['video_items']}")
    lines.append(f"items without image : {stats['no_image']}")
    lines.append("")
    lines.append("--- Translation QC (deterministic on stored translations) ---")
    lines.append(f"no issues           : {stats['translation_ok']}")
    lines.append(f"with issues         : {stats['translation_issues']}")
    golden_total = metrics.get("golden_total", 0)
    if golden_total == 0:
        lines.append("")
        lines.append("[LIMITATION] No golden labels matched real DB items — "
                     "accuracy metrics are based only on the golden set itself. "
                     "Match golden entries to real titles via match_title to get "
                     "golden accuracy on production data.")
    return "\n".join(lines)


def write_outputs(records, report_text, mode, cost):
    os.makedirs(CACHE_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = os.path.join(CACHE_DIR, f"evaluation_{mode}_{ts}")
    per_item = []
    for r in records:
        per_item.append({
            "title": (r["item"].get("title") or "")[:120],
            "key": r.get("key", ""),
            "old_status": r["old_status"],
            "source": r["item"].get("source_tag") or r["item"].get("source"),
            "deterministic": r.get("deterministic") or {},
            "hermes": r.get("hermes") or {},
            "actual_decision": r["actual_decision"],
            "golden": (r.get("golden") or {}).get("expected_decision")
            if r.get("golden") else None,
            "golden_match": bool(r.get("golden")),
            "comparison": r.get("comparison", ""),
            "needs_human_review": r.get("needs_human_review", False),
            "verification": r.get("hermes_verification") or r.get("verification") or {},
        })
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump({"mode": mode, "cost": cost.to_dict(), "items": per_item},
                  f, ensure_ascii=False, indent=1)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(report_text + "\n")
    # لینک «آخرین اجرا» برای راحتی
    latest_json = os.path.join(CACHE_DIR, f"latest_{mode}.json")
    latest_md = os.path.join(CACHE_DIR, f"latest_{mode}.md")
    import shutil
    shutil.copy(base + ".json", latest_json)
    shutil.copy(base + ".md", latest_md)
    print(f"\n[outputs] {base}.json")
    print(f"[outputs] {base}.md")
    return base


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-ai", action="store_true",
                    help="تحلیل با Hermes واقعی (هزینه دارد؛ نتیجه cache می‌شود)")
    ap.add_argument("--limit", type=int, default=0,
                    help="سقف آیتم‌های DB (پیش‌فرض: همه)")
    ap.add_argument("--verify", action="store_true",
                    help="با --with-ai، verification را هم اجرا کن (پرهزینه‌تر)")
    ap.add_argument("--no-cache", action="store_true",
                    help="نتیجه Hermes را cache نکن/نخوان")
    args = ap.parse_args()

    mode = "ai" if args.with_ai else "deterministic"
    cost = CostTracker()
    cache = {} if args.no_cache else _load_cache(mode)

    items = load_items(args.limit)
    golden_entries = load_golden()
    golden_only = [dict(g) for g in golden_entries if not g.get("match_title")]

    records = []

    # ۱) آیتم‌های واقعی DB
    for rec in items:
        item = rec["item"]
        golden = _match_golden(item.get("title") or "", golden_entries)
        rec["golden"] = golden
        records.append(rec)

    # ۲) golden entries بدون match_title — خودِ entry ارزیابی می‌شود
    for g in golden_only:
        item = {
            "source": g.get("source", ""), "source_tag": g.get("source_tag", ""),
            "url": g.get("url", ""), "title": g.get("title", ""),
            "body": g.get("body", ""), "handle": g.get("handle", ""),
        }
        records.append({"key": "golden:" + g["id"], "item": item,
                        "old_status": "golden", "golden": g,
                        "stored_analysis": None, "stored_verification": None})

    stats = {"publish": 0, "review": 0, "reject": 0, "total": 0,
             "db_total": len(items), "golden_only": len(golden_only),
             "tiers": {"low": 0, "medium": 0, "high": 0},
             "translation_ok": 0, "translation_issues": 0,
             "image_items": 0, "video_items": 0, "no_image": 0}

    for rec in records:
        item = rec["item"]
        # deterministic همیشه (بدون هزینه)
        a_det, tier = deterministic_for(item)
        stats["tiers"][tier] += 1
        rec["deterministic"] = a_det.to_dict()

        # hermes (فقط با --with-ai؛ بدون AI از stored یا خالی)
        if args.with_ai:
            key = rec.get("key") or db.make_key(item)
            a_ai, v_ai = hermes_analyze(item, cache, cost, key, args.verify)
            rec["hermes"] = a_ai
            rec["hermes_verification"] = v_ai
            actual = _decision_of(a_ai)
            needs_hr = bool((a_ai or {}).get("needs_verification"))
            if v_ai and v_ai.get("verified") is False:
                needs_hr = True
            rec["needs_human_review"] = needs_hr
            rec["comparison"] = _compare(item, rec["deterministic"], a_ai)
        else:
            rec["hermes"] = None
            actual = _decision_of(rec["deterministic"])
            rec["needs_human_review"] = actual == "review"

        # legacy comparison
        if rec["old_status"] == "sent_admin" and actual == "reject":
            rec["comparison"] = "LEGACY_SENT -> NOW_REJECTED"
        elif rec["old_status"] == "rejected" and actual in ("publish", "review"):
            rec["comparison"] = f"LEGACY_REJECTED -> NOW_{actual.upper()}"

        rec["actual_decision"] = actual
        stats["total"] += 1
        stats[actual] += 1

        if item.get("image") or item.get("images"):
            stats["image_items"] += 1
        else:
            stats["no_image"] += 1
        if item.get("video_url"):
            stats["video_items"] += 1

        tr = item.get("translated") or {}
        if tr and tr.get("body"):
            from ai.quality_control import check_facts
            issues = check_facts(item.get("body") or item.get("title") or "", tr)
            if issues:
                stats["translation_issues"] += 1
            else:
                stats["translation_ok"] += 1

    if not args.no_cache:
        _save_cache(mode, cache)

    metrics = compute_metrics(records, stats)
    report_text = build_report(records, stats, metrics, cost, mode, golden_entries)

    print(report_text)

    # گزارش دسته‌بندی (مرحله ۲۵)
    print("\n--- Category breakdown (golden) ---")
    cat_hit, cat_tot = {}, {}
    for r in records:
        g = r.get("golden")
        if not g:
            continue
        cat = g.get("category", "?")
        cat_tot[cat] = cat_tot.get(cat, 0) + 1
        if g.get("expected_decision") == r["actual_decision"]:
            cat_hit[cat] = cat_hit.get(cat, 0) + 1
    for cat in sorted(cat_tot):
        mark = "OK" if cat_hit.get(cat) == cat_tot[cat] else " "
        print(f"  [{mark}] {cat:22s} {cat_hit.get(cat,0)}/{cat_tot[cat]}")

    write_outputs(records, report_text, mode, cost)

    # diff بین deterministic و hermes (مرحله ۲۳)
    if args.with_ai:
        diffs = [r for r in records
                 if r.get("deterministic") and r.get("hermes")
                 and _decision_of(r["deterministic"]) != _decision_of(r["hermes"])]
        print(f"\n--- Deterministic vs Hermes divergence: {len(diffs)} items ---")
        for r in diffs[:12]:
            print(f"  {_decision_of(r['deterministic']):8s} -> "
                  f"{_decision_of(r['hermes']):8s} | "
                  f"{(r['item'].get('title') or '')[:60]}")

    return 0


def _compare(item: dict, det: dict, ai: dict) -> str:
    d, a = _decision_of(det), _decision_of(ai)
    if d == a:
        return f"SAME ({d})"
    return f"CHANGED: deterministic={d}, hermes={a}"


if __name__ == "__main__":
    sys.exit(main())
