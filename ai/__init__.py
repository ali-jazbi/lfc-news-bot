"""لایه هوش خبر (Hermes AI Editor).

Python = زیرساخت؛ این پکیج فقط reasoning/سردبیری است.
هر چیزی در اینجا fail-safe است: خطای AI هرگز bot را down نمی‌کند.
"""
from .schemas import (
    NewsAnalysis, VerificationResult, TranslationReview, ImageSelection,
    SchemaError,
)
from .editor import NewsEditor, deterministic_analysis, tier_of
from .tracing import trace

__all__ = [
    "NewsAnalysis", "VerificationResult", "TranslationReview", "ImageSelection",
    "SchemaError", "NewsEditor", "deterministic_analysis", "tier_of", "trace",
]


def create_editor(client=None):
    """ساخت سردبیر — client پیش‌فرض HermesClient است."""
    from .editor import NewsEditor
    return NewsEditor(client=client)
