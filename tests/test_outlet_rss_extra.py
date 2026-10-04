"""منابع RSS جدید و اختیاری (OUTLET_RSS_SOURCES) — بدون شبکه.

اصل مهم: پیش‌فرض خالی است و هیچ رفتار فعلی (فید BBC، توییتر، ...) عوض نمی‌شود.
"""
import email.utils
import time

import pytest

import config
from sources import outlet_rss


def _rfc822(hours_ago):
    return email.utils.formatdate(time.time() - hours_ago * 3600, usegmt=True)


def _entry(n, hours_ago=1, title=None):
    return {
        "title": title or f"Story {n}",
        "link": f"https://example.com/{n}",
        "summary": f"summary {n}",
        "image": None,
        "published": _rfc822(hours_ago),
    }


@pytest.fixture
def no_legacy(monkeypatch):
    monkeypatch.setattr(config, "OUTLET_RSS_FEEDS", [])
    monkeypatch.setattr(config, "OUTLET_RSS_MAX_AGE_HOURS", 12, raising=False)


def test_default_is_off_and_never_fetches(monkeypatch, no_legacy):
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES", [], raising=False)
    calls = []
    monkeypatch.setattr(outlet_rss, "parse_rss",
                        lambda url, timeout=25: calls.append(url) or [])
    assert outlet_rss.fetch_extra(limit=5) == []
    assert calls == []


def test_only_enabled_sources_are_fetched(monkeypatch, no_legacy):
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES", ["guardian"], raising=False)
    urls = []

    def fake(url, timeout=25):
        urls.append(url)
        return [_entry(1)]

    monkeypatch.setattr(outlet_rss, "parse_rss", fake)
    items = outlet_rss.fetch_extra(limit=5)
    assert urls == [outlet_rss.CATALOG["guardian"]["url"]]
    assert len(items) == 1
    assert items[0]["source_tag"] == "The Guardian"
    assert items[0]["source"] == "The Guardian"
    assert items[0]["url"] == "https://example.com/1"


def test_all_keyword_enables_every_catalog_source(monkeypatch, no_legacy):
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES", ["all"], raising=False)
    urls = []
    monkeypatch.setattr(outlet_rss, "parse_rss",
                        lambda url, timeout=25: urls.append(url) or [])
    outlet_rss.fetch_extra(limit=5)
    assert set(urls) == {v["url"] for v in outlet_rss.CATALOG.values()}


def test_unknown_id_is_ignored_not_fatal(monkeypatch, no_legacy):
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES",
                        ["nope", "football365"], raising=False)
    monkeypatch.setattr(outlet_rss, "parse_rss",
                        lambda url, timeout=25: [_entry(1)])
    items = outlet_rss.fetch_extra(limit=5)
    assert [i["source_tag"] for i in items] == ["Football365"]


def test_ids_are_case_and_space_insensitive(monkeypatch, no_legacy):
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES",
                        [" Guardian "], raising=False)
    monkeypatch.setattr(outlet_rss, "parse_rss",
                        lambda url, timeout=25: [_entry(1)])
    assert len(outlet_rss.fetch_extra(limit=5)) == 1


def test_each_source_has_its_own_limit(monkeypatch, no_legacy):
    """سقف برای هر منبع جداست؛ یک فید شلوغ فیدهای بعدی را گرسنه نمی‌گذارد."""
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES",
                        ["football365", "guardian"], raising=False)
    monkeypatch.setattr(outlet_rss, "parse_rss",
                        lambda url, timeout=25: [_entry(i) for i in range(10)])
    items = outlet_rss.fetch_extra(limit=3)
    tags = [i["source_tag"] for i in items]
    assert tags.count("Football365") == 10
    assert tags.count("The Guardian") == 10


def test_old_entries_are_dropped_but_undated_are_kept(monkeypatch, no_legacy):
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES", ["guardian"], raising=False)
    monkeypatch.setattr(config, "OUTLET_RSS_MAX_AGE_HOURS", 12, raising=False)
    undated = _entry(3)
    undated["published"] = ""
    garbage = _entry(4)
    garbage["published"] = "not a date"
    monkeypatch.setattr(outlet_rss, "parse_rss", lambda url, timeout=25: [
        _entry(1, hours_ago=2),      # تازه → می‌ماند
        _entry(2, hours_ago=30),     # کهنه → حذف
        undated,                     # بدون تاریخ → می‌ماند
        garbage,                     # تاریخ نامعتبر → می‌ماند
    ])
    urls = [i["url"] for i in outlet_rss.fetch_extra(limit=10)]
    assert urls == ["https://example.com/1", "https://example.com/2", "https://example.com/3",
                    "https://example.com/4"]


def test_age_filter_can_be_disabled(monkeypatch, no_legacy):
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES", ["guardian"], raising=False)
    monkeypatch.setattr(config, "OUTLET_RSS_MAX_AGE_HOURS", 0, raising=False)
    monkeypatch.setattr(outlet_rss, "parse_rss",
                        lambda url, timeout=25: [_entry(1, hours_ago=500)])
    assert len(outlet_rss.fetch_extra(limit=5)) == 1


def test_team_specific_catalog_feeds_skip_keyword_filter(monkeypatch, no_legacy):
    """This Is Anfield مخصوص لیورپول است؛ خبری بدون کلمه‌ی «liverpool» هم می‌ماند."""
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES",
                        ["thisisanfield"], raising=False)
    monkeypatch.setattr(outlet_rss, "parse_rss", lambda url, timeout=25: [
        _entry(1, title="Konate injury update ahead of weekend")])
    assert len(outlet_rss.fetch_extra(limit=5)) == 1


def test_one_dead_feed_does_not_block_others(monkeypatch, no_legacy):
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES",
                        ["football365", "guardian"], raising=False)

    def fake(url, timeout=25):
        if "football365" in url:
            raise ConnectionError("dead")
        return [_entry(1)]

    monkeypatch.setattr(outlet_rss, "parse_rss", fake)
    items = outlet_rss.fetch_extra(limit=5)
    assert [i["source_tag"] for i in items] == ["The Guardian"]


def test_feed_already_in_legacy_list_is_not_fetched_twice(monkeypatch):
    url = outlet_rss.CATALOG["guardian"]["url"]
    monkeypatch.setattr(config, "OUTLET_RSS_FEEDS", [url])
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES", ["guardian"], raising=False)
    calls = []
    monkeypatch.setattr(outlet_rss, "parse_rss",
                        lambda u, timeout=25: calls.append(u) or [_entry(1)])
    assert outlet_rss.fetch_extra(limit=5) == []
    assert calls == []


def test_legacy_fetch_is_untouched_by_new_sources(monkeypatch):
    """fetch() قدیمی فقط OUTLET_RSS_FEEDS را می‌خواند، حتی با فعال بودن منابع جدید."""
    monkeypatch.setattr(config, "OUTLET_RSS_FEEDS", ["https://bbc.example/liverpool/rss"])
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES", ["all"], raising=False)
    calls = []
    monkeypatch.setattr(outlet_rss, "parse_rss",
                        lambda u, timeout=25: calls.append(u) or [_entry(1)])
    outlet_rss.fetch(limit=5)
    assert calls == ["https://bbc.example/liverpool/rss"]


def test_main_registers_extra_source_last_and_only_when_configured(monkeypatch):
    import main
    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES", [], raising=False)
    ids_off = [sid for sid, _, _ in main._sources()]
    assert "rss_extra" not in ids_off

    monkeypatch.setattr(config, "OUTLET_RSS_SOURCES", ["guardian"], raising=False)
    ids_on = [sid for sid, _, _ in main._sources()]
    assert ids_on[-1] == "rss_extra"
    # منابع قبلی دقیقاً همان‌ها و با همان ترتیب می‌مانند
    assert ids_on[:-1] == ids_off
