"""تست‌های انتخاب عکس (مرحله ۷/۱۵): بدون عکس، چند کاندیدا، عکس اشتباه،
اعتماد پایین، شکست دانلود."""
import pytest

from ai.image_selector import select_image, candidate_images
from ai.schemas import ImageSelection


def test_no_image_no_candidates(monkeypatch):
    monkeypatch.setattr("config.ENABLE_AUTO_IMAGE", False)
    item = {"title": "News", "body": "x", "url": "https://x/1"}
    urls, sel = select_image(item, editor=None)
    assert urls is None


def test_source_image_kept_when_ai_off(monkeypatch):
    monkeypatch.setattr("config.HERMES_ENABLED", False)
    item = {"title": "News", "body": "x", "url": "https://x/1",
            "image": "https://img/photo.jpg"}
    urls, sel = select_image(item, editor=None)
    assert urls == "https://img/photo.jpg"


def test_ai_selects_best_candidate(fake_hermes, monkeypatch):
    monkeypatch.setattr("config.HERMES_ENABLED", True)
    monkeypatch.setattr("config.IMAGE_MIN_CONFIDENCE", 0.6)
    fake_hermes.image = ImageSelection(
        image_url="https://img/2.jpg", confidence=0.91, reason="player match")
    from ai.editor import NewsEditor
    editor = NewsEditor(client=fake_hermes)
    item = {"title": "Mohamed Salah injury", "body": "Salah injured in training",
            "url": "https://x/1",
            "images": ["https://img/1.jpg", "https://img/2.jpg"]}
    urls, sel = select_image(item, editor)
    assert urls == "https://img/2.jpg"
    assert sel.confidence == 0.91


def test_wrong_image_rejected_low_confidence(fake_hermes, monkeypatch):
    monkeypatch.setattr("config.HERMES_ENABLED", True)
    monkeypatch.setattr("config.IMAGE_MIN_CONFIDENCE", 0.6)
    fake_hermes.image = ImageSelection(
        image_url=None, confidence=0.2, reason="unrelated stock photo")
    from ai.editor import NewsEditor
    editor = NewsEditor(client=fake_hermes)
    item = {"title": "Liverpool news", "body": "x", "url": "https://x/1",
            "images": ["https://img/stock.jpg"]}
    urls, sel = select_image(item, editor)
    assert urls is None  # بهتر بدون عکس تا عکس اشتباه


def test_never_random_image(fake_hermes, monkeypatch):
    """اصل: هرگز عکس تصادفی فقط چون عکسی وجود دارد."""
    monkeypatch.setattr("config.HERMES_ENABLED", True)
    fake_hermes.image = ImageSelection(
        image_url=None, confidence=0.4, reason="no clearly relevant image")
    from ai.editor import NewsEditor
    editor = NewsEditor(client=fake_hermes)
    item = {"title": "Liverpool match report", "body": "x", "url": "https://x/1",
            "images": ["https://img/unrelated.jpg"]}
    urls, _ = select_image(item, editor)
    assert urls is None


def test_image_download_failure_keeps_source(monkeypatch):
    """شکست ارزیابی AI → عکس خودِ منبع می‌ماند، نه عکس جدید."""
    monkeypatch.setattr("config.HERMES_ENABLED", True)

    class FailClient:
        def select_image(self, item, candidates):
            raise RuntimeError("vision API down")

    from ai.editor import NewsEditor
    editor = NewsEditor(client=FailClient())
    item = {"title": "Liverpool news", "body": "x", "url": "https://x/1",
            "image": "https://img/source.jpg"}
    urls, sel = select_image(item, editor)
    assert urls == "https://img/source.jpg"


def test_candidate_images_dedup():
    item = {"title": "t", "body": "x", "url": "https://x/1",
            "image": "https://img/a.jpg",
            "images": ["https://img/a.jpg", "https://img/b.jpg"]}
    cands = candidate_images(item)
    assert cands[0] == "https://img/a.jpg"
    assert len(cands) == 2
