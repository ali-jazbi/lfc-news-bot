"""تست‌های جلوگیری از خبر تکراری (مرحله ۱۵)."""
import time


def test_exact_duplicate(news_db):
    item = {"source": "X", "source_tag": "A", "url": "https://a.com/1",
            "title": "Liverpool sign new player", "body": "text"}
    assert not news_db.is_duplicate(item)
    news_db.save(item, status="sent_admin")
    assert news_db.is_duplicate(item)


def test_url_duplicate_normalized(news_db):
    a = {"source": "X", "source_tag": "A", "url": "https://www.A.com/1/",
         "title": "Story one", "body": "x"}
    b = {"source": "X", "source_tag": "A", "url": "http://a.com/1",
         "title": "Story one", "body": "x"}
    assert not news_db.is_duplicate(a)
    news_db.save(a, status="sent_admin")
    assert news_db.is_duplicate(b)  # همان URL با www/تریلینگ اسلش


def test_content_duplicate_similar_headline(news_db):
    a = {"source": "X", "source_tag": "A", "url": "https://a.com/1",
         "title": "Liverpool agree deal to sign Brazilian forward",
         "body": "text"}
    b = {"source": "X", "source_tag": "A", "url": "https://a.com/2",
         "title": "Liverpool agree deal to sign Brazilian forward",
         "body": "same story"}
    assert not news_db.is_duplicate(a)
    news_db.save(a, status="sent_admin")
    assert not news_db.is_duplicate(b)
    assert news_db.similar_sources(b, exclude_self=False)


def test_same_story_different_source_not_duplicate(news_db):
    """DUPLICATE_SCOPE=source: دو منبع مختلف روی یک خبر → هر دو می‌آیند."""
    import config
    assert getattr(config, "DUPLICATE_SCOPE", "source") == "source"
    a = {"source": "X", "source_tag": "Fabrizio Romano",
         "url": "https://a.com/1",
         "title": "Liverpool working on Barcola deal", "body": "x"}
    b = {"source": "X", "source_tag": "David Ornstein",
         "url": "https://a.com/2",
         "title": "Liverpool working on Barcola deal", "body": "x"}
    news_db.save(a)
    assert not news_db.is_duplicate(b)


def test_old_article_not_duplicate(news_db):
    """خبر قدیمی‌تر از ۴۸ ساعت → تکراری حساب نمی‌شود."""
    a = {"source": "X", "source_tag": "A", "url": "https://a.com/1",
         "title": "Liverpool win the match", "body": "x"}
    news_db.save(a)
    # created_at را ۳ روز عقب ببر
    news_db._c().execute(
        "UPDATE items SET created_at=? WHERE url=?",
        (time.time() - 3 * 86400, "https://a.com/1"))
    news_db._c().commit()
    b = dict(a)
    b["url"] = "https://a.com/2"
    assert not news_db.is_duplicate(b)


def test_make_key_stable(news_db):
    import db
    assert db.make_key({"url": "https://x.com/a/status/1",
                        "title": "t"}) == db.make_key(
        {"url": "https://x.com/a/status/1", "title": "t"})


def test_article_identity_query_is_not_tracking(news_db):
    assert news_db.normalize_url('https://example.test/article?id=1&utm_source=x') == 'https://example.test/article?id=1'
    assert news_db.make_key({'url':'https://example.test/article?id=1'}) != news_db.make_key({'url':'https://example.test/article?id=2'})

def test_failed_item_is_not_an_exact_published_duplicate(news_db):
    item = {'url': 'https://example.test/failed', 'title': 'Liverpool news'}
    news_db.save(item, status='failed')
    assert not news_db.is_duplicate(item)
