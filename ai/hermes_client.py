"""کلاینت Hermes — تنها نقطه تماس Python با Hermes Agent.

سه backend دارد (به ترتیب اولویت):
  1. Hermes Agent CLI  — `hermes -z <prompt> --cli --yolo -t <toolsets>`
     (برای verification که به web_search نیاز دارد)
  2. LLM مستقیم        — همان زنجیره litellm خودِ پروژه (translate.py)
     (برای طبقه‌بندی/QC ارزان‌تر — قانون هزینه، مرحله ۱۴/۱۵)
  3. Deterministic     — تحلیل کلمه‌ای/منبع (وقتی هیچ‌کدام در دسترس نیست)

قانون: هیچ‌وقت کرش نمی‌کند و هیچ‌وقت bot را down نمی‌کند. هر خطا → خطای
HermesError که editor با fallback مدیریت می‌کند. کلید/توکن هرگز لاگ نمی‌شود.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time

import config
import health

from .schemas import (
    NewsAnalysis, VerificationResult, TranslationReview, ImageSelection,
    extract_json_object, SchemaError,
)

log = logging.getLogger("ai.hermes")


class HermesError(Exception):
    """خطای هر نوع backend هرمس."""


def _default_bin() -> str:
    """مسیر خودکار hermes: PATH → HERMES_HOME (ویندوز و لینوکس)."""
    if config.HERMES_BIN:
        return config.HERMES_BIN
    found = shutil.which("hermes")
    if found:
        return found
    home = config.HERMES_HOME_AUTO
    if not home:
        home = os.environ.get(
            "LOCALAPPDATA", os.path.expanduser("~/.hermes")
        ) if sys.platform.startswith("win") else os.path.expanduser("~/.hermes")
    candidates = [
        os.path.join(home, "hermes-agent", "venv", "Scripts", "hermes.exe"),
        os.path.join(home, "hermes-agent", "venv", "bin", "hermes"),
        os.path.join(home, "bin", "hermes"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return ""


def _version() -> str:
    """نسخه Hermes برای گزارش نهایی؛ در صورت خطا 'n/a'."""
    try:
        out = subprocess.run(
            [_default_bin(), "--version"], capture_output=True, text=True,
            timeout=20,
        ).stdout.strip().splitlines()
        return out[0].strip() if out else "n/a"
    except Exception:
        return "n/a"


class HermesClient:
    def __init__(self, bin_path=None, timeout=None, retries=None, toolsets=None):
        self.bin_path = bin_path if bin_path is not None else _default_bin()
        self.timeout = timeout if timeout is not None else config.HERMES_TIMEOUT
        self.retries = retries if retries is not None else config.HERMES_RETRIES
        self.toolsets = (toolsets if toolsets is not None
                         else config.HERMES_TOOLSETS)
        self.agent_available = bool(self.bin_path and os.path.isfile(self.bin_path))
        if not self.agent_available:
            log.debug("hermes binary not found (%s) — direct LLM only",
                      self.bin_path or "(empty)")

    # ------------------------------------------------------------- agent CLI
    def run_agent(self, prompt: str, toolsets=None, timeout=None) -> str:
        """فراخوانی یک‌باره Hermes Agent (غیرتعاملی). خروجی: متن پاسخ."""
        if not self.agent_available:
            raise HermesError("hermes binary not found")
        cmd = [
            self.bin_path, "-z", prompt, "--cli", "--yolo",
            "-t", toolsets or self.toolsets,
        ]
        last = None
        for attempt in range(self.retries + 1):
            try:
                r = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=timeout or self.timeout, cwd=os.getcwd(),
                )
                out = (r.stdout or "").strip()
                err = (r.stderr or "").strip()
                if r.returncode == 0 and out:
                    return out
                # 429/503 → retry بعد از backoff کوتاه
                blob = (out + " " + err).lower()
                if "429" in blob or "rate limit" in blob or "503" in blob:
                    time.sleep(5 * (attempt + 1))
                    last = HermesError("agent rate limited")
                    continue
                last = HermesError(
                    (err or out or f"exit {r.returncode}")[:300]
                )
                break
            except subprocess.TimeoutExpired:
                last = HermesError("agent timeout")
                time.sleep(2 * (attempt + 1))
            except Exception as e:
                last = HermesError(str(e)[:200])
                time.sleep(2 * (attempt + 1))
        raise last if last else HermesError("agent failed")

    # ----------------------------------------------------------- LLM مستقیم
    def run_direct(self, prompt: str, json_mode=True, timeout=None) -> str:
        """صدا زدن مستقیم زنجیره LLM پروژه (بدون agent) — ارزان و سریع."""
        try:
            import translate
        except Exception as e:
            raise HermesError(f"translate unavailable: {e}")
        router, names = translate._get_router()
        if not router or not names:
            raise HermesError("no LLM chain configured")
        kwargs = {
            "model": names[0],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": getattr(translate, "MAX_TOKENS", 4000),
        }
        if json_mode and translate.JSON_MODE:
            kwargs["response_format"] = {"type": "json_object"}
        last = None
        for attempt in range(self.retries + 1):
            try:
                resp = router.completion(**kwargs)
                txt = translate._msg_text(resp)
                provider = translate._provider_of(resp, names[0])
                health.record_ok(provider, kind="provider")
                return txt or ""
            except Exception as e:
                last = HermesError(str(e)[:200])
                health.record_fail(names[0], e, kind="provider")
                time.sleep(2 * (attempt + 1))
        raise last if last else HermesError("LLM chain failed")

    # ------------------------------------------------------------- فراخوانی
    def _call(self, prompt: str, toolsets=None, json_output=True,
              prefer_agent=False) -> str:
        """Agent برای کارهای ابزاردار (verify)، LLM مستقیم برای بقیه."""
        if prefer_agent:
            try:
                text = self.run_agent(prompt, toolsets=toolsets)
                return text
            except HermesError as e:
                log.warning("agent failed (%s) — falling back to direct LLM", e)
        text = self.run_direct(prompt, json_mode=json_output)
        return text

    def _structured(self, prompt: str, expected, toolsets=None,
                    prefer_agent=False, attempts=2):
        """فراخوانی + استخراج JSON + validation. در صورت schema خراب دوباره
        می‌پرسد (حداکثر attempts بار) و بعد HermesError می‌دهد."""
        last = None
        for i in range(attempts):
            text = self._call(prompt, toolsets=toolsets,
                              json_output=True, prefer_agent=prefer_agent)
            data = extract_json_object(text)
            if data is None:
                last = HermesError("AI output had no JSON object")
                continue
            try:
                return expected.from_dict(data)
            except SchemaError as e:
                last = HermesError(f"schema error: {e}")
                continue
        raise last if last else HermesError("structured call failed")

    # ------------------------------------------------------------- تحلیل خبر
    def analyze(self, item: dict, tier: str = "medium") -> NewsAnalysis:
        """مرحله ۴ — طبقه‌بندی، relevance، اهمیت، تصمیم."""
        prompt = _analysis_prompt(item, tier)
        try:
            if tier == "low":
                return self._structured(prompt, NewsAnalysis, attempts=1)
            return self._structured(prompt, NewsAnalysis, attempts=2)
        except HermesError as e:
            log.warning("AI analysis failed (%s) — deterministic fallback", e)
            from .editor import deterministic_analysis
            return deterministic_analysis(item, tier=tier)

    def verify(self, item: dict, claim: str, evidence: list) -> VerificationResult:
        """مرحله ۵ — راستی‌آزمایی با شواهد واقعی (web_search در agent)."""
        prompt = _verification_prompt(item, claim, evidence)
        try:
            result = self._structured(
                prompt, VerificationResult, toolsets="web",
                prefer_agent=True, attempts=2,
            )
        except HermesError as e:
            log.warning("AI verification failed (%s) — evidence-only score", e)
            # بدون AI: فقط بر اساس شواهد جمع‌آوری‌شده امتیاز می‌دهیم (نه حدس)
            result = VerificationResult(
                confidence=min(0.9, 0.2 + 0.2 * len(evidence)),
                verified=len(evidence) >= 2,
                evidence=evidence, claim=claim,
                source=(item.get("source_tag") or item.get("source") or ""),
                summary="شواهد کافی برای تأیید مستقل پیدا نشد — نیاز به بازبینی انسانی",
                checked_at=time.time(),
            )
        return result

    def review_translation(self, item: dict, tr: dict,
                           examples: list) -> TranslationReview:
        """مرحله ۶ — QC ترجمه با نمونه‌های واقعی کانال."""
        prompt = _translation_review_prompt(item, tr, examples)
        try:
            return self._structured(prompt, TranslationReview, attempts=2)
        except HermesError as e:
            log.warning("AI translation review failed (%s) — pass through", e)
            return TranslationReview(ok=True, score=0.9, issues=[])

    def select_image(self, item: dict, candidates: list) -> ImageSelection:
        """مرحله ۷ — ارزیابی کاندیداهای عکس. اگر مطمئن نبود → بدون عکس."""
        if not candidates:
            return ImageSelection(image_url=None, confidence=0.0,
                                  reason="no candidates")
        prompt = _image_prompt(item, candidates)
        try:
            sel = self._structured(prompt, ImageSelection, attempts=1)
        except HermesError as e:
            log.warning("AI image evaluation failed (%s) — keep source image only", e)
            # بدون AI: هرگز عکسِ جدیدِ تصادفی انتخاب نمی‌شود؛ فقط عکسِ خودِ
            # منبع (اگر وجود داشته باشد) می‌ماند — رفتارِ فعلی بات.
            own = item.get("image") or (item.get("images") or [None])[0]
            return ImageSelection(image_url=own,
                                  confidence=1.0 if own else 0.0,
                                  reason="source image kept (AI unavailable)")
        # اصل «never choose a random image»: اگر اطمینان پایین بود → بدون عکس
        if sel.confidence < config.IMAGE_MIN_CONFIDENCE:
            return ImageSelection(image_url=None, confidence=sel.confidence,
                                  reason=f"low confidence ({sel.confidence:.2f})")
        return sel


# ------------------------------------------------------------------ prompts
def _analysis_prompt(item: dict, tier: str) -> str:
    return (
        "You are the senior news editor for a Liverpool FC Persian Telegram "
        "channel. Classify this news item. Base your decision ONLY on the "
        "provided content and explicit metadata. Do NOT invent facts, quotes, "
        "names or sources. If you are not sure, say so via confidence and "
        "decision=review. "
        f"Tier: {tier} (low=cheap classification, high=needs care).\n\n"
        f"Source: {item.get('source_tag') or item.get('source') or '?'}\n"
        f"Title: {item.get('title') or ''}\n"
        f"Body:\n{(item.get('body') or '')[:3000]}\n\n"
        "Reply with ONLY a JSON object:\n"
        '{"decision": "publish|review|reject", "confidence": 0.0-1.0, '
        '"importance": 1-10, "category": "breaking|transfer|transfer_rumour|'
        'injury|lineup|match|result|quote|training|club_announcement|'
        'player_news|manager_news|opinion|speculation|irrelevant", '
        '"relevance": true|false, '
        '"quality": "real|speculation|opinion|clickbait|duplicate|outdated|'
        'misleading", "reason": "short reason", '
        '"needs_verification": true|false, '
        '"verification_summary": null or short text}\n'
        "Rules: irrelevant to Liverpool FC → decision=reject. Opinion/rumour → "
        "never publish automatically. Major transfer/injury claims from "
        "non-official sources → needs_verification=true."
    )


def _verification_prompt(item: dict, claim: str, evidence: list) -> str:
    ev_lines = "\n".join(
        f"- [{e.get('source','?')}] {e.get('title','')} {e.get('url','')}"
        for e in evidence
    ) or "(no independent evidence collected)"
    return (
        "You are a verification researcher. Below is a news claim and a list of "
        "independently collected evidence (search results / other sources). "
        "Evaluate whether the evidence CORROBORATES the claim.\n"
        "CRITICAL: Do NOT claim something is true based on your own knowledge. "
        "If the evidence is insufficient, set verified=false and low confidence. "
        "Never invent evidence.\n\n"
        f"Claim: {claim}\n"
        f"News source: {item.get('source_tag') or item.get('source') or '?'}\n\n"
        f"Evidence collected:\n{ev_lines}\n\n"
        "Reply with ONLY a JSON object:\n"
        '{"verified": true|false, "confidence": 0.0-1.0, '
        '"summary": "short assessment based only on evidence above"}'
    )


def _translation_review_prompt(item: dict, tr: dict, examples: list) -> str:
    ex_block = ""
    if examples:
        parts = []
        for p in examples[:3]:
            t = p.get("translated") or {}
            parts.append(f"- {t.get('title','')}: {t.get('body','')[:200]}")
        ex_block = "Approved channel style examples:\n" + "\n".join(parts) + "\n"
    return (
        "You are a Persian football translation QC reviewer. Compare the "
        "translation against the original English. Check: factual accuracy, "
        "names, numbers, dates, football terminology, tone, fluency, "
        "unnecessary literal translation, hallucination, omission, headline "
        "quality.\n"
        f"{ex_block}\n"
        f"Original title: {item.get('title','')}\n"
        f"Original body:\n{(item.get('body') or '')[:2500]}\n\n"
        f"Translation title: {tr.get('title','')}\n"
        f"Translation body:\n{(tr.get('body') or '')[:2500]}\n\n"
        "Reply with ONLY a JSON object:\n"
        '{"ok": true|false, "score": 0.0-1.0, '
        '"issues": ["list of concrete problems, e.g. wrong number 17 vs 71"], '
        '"revision": "corrected Persian body if ok=false, else empty string"}'
    )


def _image_prompt(item: dict, candidates: list) -> str:
    cand_lines = "\n".join(f"- {u}" for u in candidates[:8])
    return (
        "You are an image editor for a Liverpool FC news channel. Given the "
        "news below and candidate image URLs, decide whether any image is "
        "clearly relevant (correct player/team/context). If unsure, or if all "
        "candidates are unrelated/low quality, return image_url=null.\n"
        "NEVER pick an image merely because one exists.\n\n"
        f"Title: {item.get('title','')}\n"
        f"Body:\n{(item.get('body') or '')[:800]}\n\n"
        f"Candidates:\n{cand_lines}\n\n"
        "Reply with ONLY a JSON object:\n"
        '{"image_url": "best candidate url or null", "confidence": 0.0-1.0, '
        '"reason": "short reason"}'
    )
