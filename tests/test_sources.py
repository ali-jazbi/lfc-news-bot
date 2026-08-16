"""تست‌های منابع (مرحله ۱۵): RSS موفق/تایم‌اوت/خراب/500/در دسترس نبودن/
fallback/retry/همزمانی."""
import time

import pytest


# ------------------------------------------------------------- parse_rss
def test_rss_success(monkeypatch):
    from sources.base import parse_rss
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>BBC</title>
      <item><title>Liverpool news</title>
        <link>https://bbc.com/1</link>
        <description>Liverpool win again</description></item>
    </channel></rss>"""
    monkeypatch.setattr("sources.base.http_get", lambda url, timeout=25: xml)
    items = parse_rss("https://feed.example/rss")
    assert len(items) == 1
    assert items[0]["title"] == "Liverpool news"


def test_rss_timeout(monkeypatch, tmp_path):
    """timeout منبع اعمال می‌شود و خواندن آویزان نمی‌ماند."""
    import sys
    from sources.base import parse_rss

    # فیک feedparser تا بعد از timeout شبکهٔ واقعی نزند
    class FakeFeed:
        entries = []

    monkeypatch.setitem(sys.modules, "feedparser",
                        type("fp", (), {"parse": lambda *a, **k: FakeFeed()}))

    def slow(url, timeout=25):
        time.sleep(timeout)
        return None

    monkeypatch.setattr("sources.base.http_get", slow)
    t0 = time.time()
    items = parse_rss("https://feed.example/rss", timeout=1)
    assert items == []
    assert time.time() - t0 < 1.6  # timeout واقعاً اعمال می‌شود


def test_rss_malformed(monkeypatch):
    from sources.base import parse_rss
    monkeypatch.setattr("sources.base.http_get",
                        lambda url, timeout=25: "<not rss at all")
    assert parse_rss("https://feed.example/rss") == []


def test_rss_http_500(monkeypatch):
    from sources.base import http_get

    class R:
        status_code = 500
        text = "server error"

    monkeypatch.setattr("sources.base._session", type("S", (), {
        "get": lambda self, url, timeout=25: R()})())
    assert http_get("https://feed.example/rss") is None


def test_rss_source_unavailable(monkeypatch):
    from sources.base import http_get

    def boom(url, timeout=25):
        raise ConnectionError("network down")

    monkeypatch.setattr("sources.base._session",
                        type("S", (), {"get": boom})())
    assert http_get("https://feed.example/rss") is None


# ----------------------------------------------------------- source_health
def test_source_health_backoff(news_db):
    import source_health
    s = source_health.record("feed_a", ok=False)
    assert s == "degraded"
    source_health.record("feed_a", ok=False)
    for _ in range(3):
        s = source_health.record("feed_a", ok=False)
    assert s == "failed"  # ۵ شکست پشت‌سرهم → failed
    info = news_db.source_health_status("feed_a")
    assert info["consecutive_failures"] == 5
    assert info["total_failures"] == 5
    # backoff → هنوز due نیست
    assert not source_health.is_due("feed_a")
    # سالم شدن → healthy و دوباره due
    source_health.mark_ok("feed_a", items=2, latency_ms=10)
    assert source_health.is_due("feed_a")
    assert news_db.source_health_status("feed_a")["status"] == "healthy"


def test_source_failure_does_not_block_pipeline(monkeypatch, tmp_db):
    """یک منبع خراب نباید بقیه را متوقف کند (مرحله ۹)."""
    import main
    import source_health

    calls = {"bad": 0, "good": 0}

    def bad_fn(limit=6):
        calls["bad"] += 1
        raise RuntimeError("boom")

    def good_fn(limit=6):
        calls["good"] += 1
        return [{"source": "G", "source_tag": "Good", "url": "https://g/1",
                 "title": "Good news", "body": "text"}]

    monkeypatch.setattr(main, "_sources", lambda: [
        ("bad_src", "منبع خراب", bad_fn),
        ("good_src", "منبع خوب", good_fn),
    ])
    items = main.collect()
    assert len(items) == 1
    assert items[0]["source"] == "G"
    assert calls["bad"] == 1 and calls["good"] == 1


def test_source_fallback_outlet(monkeypatch):
    """outlet_rss: اگر فید اول fail شد، فید بعدی همان سیکل خوانده می‌شود."""
    from sources import outlet_rss
    import config

    def fake_parse(url, timeout=25):
        if "dead.example" in url:
            raise ConnectionError("dead")
        return [{"title": "Liverpool win", "link": "https://ok/1",
                 "summary": "Liverpool win again", "image": None}]

    monkeypatch.setattr(outlet_rss, "parse_rss", fake_parse)
    monkeypatch.setattr(config, "OUTLET_RSS_FEEDS",
                        ["https://dead.example/rss", "https://ok.example/rss"])
    items = outlet_rss.fetch(limit=5)
    assert len(items) == 1
    assert items[0]["title"] == "Liverpool win"


def test_concurrent_collect_respects_order(monkeypatch, tmp_db):
    """همزمانی: ترتیب منابع حفظ می‌شود (order deterministic)."""
    import main

    def slow_fn(limit=6):
        time.sleep(0.2)
        return [{"source": "S1", "source_tag": "S1", "url": "https://s/1",
                 "title": "first", "body": "x"}]

    def fast_fn(limit=6):
        return [{"source": "S2", "source_tag": "S2", "url": "https://s/2",
                 "title": "second", "body": "x"}]

    monkeypatch.setattr(main, "_sources", lambda: [
        ("a", "A", slow_fn), ("b", "B", fast_fn)])
    items = main.collect()
    assert [i["source"] for i in items] == ["S1", "S2"]


def test_outlet_rss_filters_irrelevant(monkeypatch):
    from sources import outlet_rss
    import config

    def fake_parse(url, timeout=25):
        return [
            {"title": "Liverpool FC news today", "link": "https://x/1",
             "summary": "Liverpool update", "image": None},
            {"title": "Manchester United transfer latest", "link": "https://x/2",
             "summary": "United news", "image": None},
        ]

    monkeypatch.setattr(outlet_rss, "parse_rss", fake_parse)
    monkeypatch.setattr(config, "OUTLET_RSS_FEEDS",
                        ["https://general.example/rss"])
    items = outlet_rss.fetch(limit=5)
    assert len(items) == 1
    assert "Liverpool" in items[0]["title"]
