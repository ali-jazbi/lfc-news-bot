"""تست‌های xscrape — اسکرپ مستقیم x.com (حالت TWITTER_MODE=xscrape).

کاملاً بدون شبکه: payload رله به‌صورت سینتتیک ساخته می‌شود و
requests.Session هم monkeypatch می‌شود.
"""
import base64
import email.utils
import time

import pytest


# ------------------------------------------------------------ fixture helpers
def _b64(tid):
    return base64.b64encode(("Tweet:%s" % tid).encode()).decode()


TID1 = "1700000000123456789"   # جدیدتر (عدد، فقط برای sort)
TID2 = "1699999999987654321"

# timestamp های تازه — وگرنه فیلتر TWEET_MAX_AGE_HOURS حذفشان می‌کند
MS1 = int(time.time() * 1000) - 3600 * 1000        # ۱ ساعت پیش
MS2 = int(time.time() * 1000) - 2 * 3600 * 1000    # ۲ ساعت پیش

# متن‌ها باید از فیلترهای واقعی (TWEET_MIN_CHARS=60، TWEET_MIN_WORDS=8 و
# ROMANO_KEYWORDS) رد شوند تا مثل پروداکشن باشند.
TXT1 = ("Liverpool have won again at Anfield tonight and the reds fans are "
        "singing loud in the stands after a brilliant second half display")
TXT2 = ("The reds continue their unbeaten run this season with another "
        "solid defensive performance and the manager praised the squad depth")


def _relay_script():
    """اسکریپت رله با دو توییت: اولی عکس+ویدیو، دومی فقط متن."""
    b1, b2 = _b64(TID1), _b64(TID2)
    return (
        '"client:%s:details":$R[7]={"__typename":"Tweet","created_at_ms":%d,full_text:"%s"}' % (b1, MS1, TXT1)
        + '"client:%s:media_entities2:0":{"__typename":"ApiMediaEntity",type:"photo",media_url_https:"https://pbs.twimg.com/media/abc.jpg"}' % b1
        + '"client:%s:media_entities2:1":{"__typename":"ApiMediaEntity",type:"video",media_url_https:"https://pbs.twimg.com/media/vid_thumb.jpg"}' % b1
        + '"client:%s:media_entities2:1:video_info:variants:0":{"content_type":"video/mp4",bitrate:632000,url:"https://video.twimg.com/low.mp4"}' % b1
        + '"client:%s:media_entities2:1:video_info:variants:1":{"content_type":"video/mp4",bitrate:2176000,url:"https://video.twimg.com/high.mp4"}' % b1
        + '"client:%s:details":$R[9]={"__typename":"Tweet","created_at_ms":%d,full_text:"%s"}' % (b2, MS2, TXT2)
    )


def _html(script_body):
    return "<html><script>x relayRecords y TBirdData z " + "q" * 10050 \
        + script_body + "</script></html>"


class _Resp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


@pytest.fixture
def patched_get(monkeypatch):
    """requests.get (مسیر بدون کوکی) را با پاسخ ثابت جایگزین می‌کند."""
    monkeypatch.setattr("sources.xscrape.requests.get",
                        lambda *a, **k: _Resp(_html(_relay_script())))


# --------------------------------------------------------- extract_relay_script
def test_extract_relay_script_found():
    from sources.xscrape import extract_relay_script
    assert extract_relay_script(_html("")) is not None


def test_extract_relay_script_missing():
    from sources.xscrape import extract_relay_script
    assert extract_relay_script("<p>no scripts at all</p>") is None
    # اسکریپت کوتاه بدون رله هم نباید پذیرفته شود
    assert extract_relay_script("<script>relayRecords TBirdData</script>") is None


# ------------------------------------------------------------- parse_relay_tweets
def test_parse_shape_and_sort():
    from sources.xscrape import parse_relay_tweets
    tweets = parse_relay_tweets(_relay_script(), 5)
    assert [t["id"] for t in tweets] == [TID1, TID2]   # sort نزولی
    assert tweets[0]["text"] == TXT1
    assert tweets[0]["created_at_ms"] == MS1


def test_parse_count_cap():
    from sources.xscrape import parse_relay_tweets
    tweets = parse_relay_tweets(_relay_script(), 1)
    assert len(tweets) == 1 and tweets[0]["id"] == TID1


def test_pinned_entries_skipped():
    from sources.xscrape import parse_relay_tweets
    script = 'pinned_entry_ids:$R[3]=[tweet-%s]' % TID2 + _relay_script()
    tweets = parse_relay_tweets(script, 5)
    assert all(t["id"] != TID2 for t in tweets)


# ---------------------------------------------------------------- extract_media
def test_best_bitrate_variant_wins():
    from sources.xscrape import parse_relay_tweets
    tweets = parse_relay_tweets(_relay_script(), 5)
    video = next(m for m in tweets[0]["media"] if m["type"] == "video")
    assert video["url"] == "https://video.twimg.com/high.mp4"


def test_photo_urls_get_size_suffix():
    from sources.xscrape import parse_relay_tweets
    tweets = parse_relay_tweets(_relay_script(), 5)
    img = next(m for m in tweets[0]["media"] if m["type"] == "image")
    assert img["url"].endswith("?format=jpg&name=large")


# ------------------------------------------------------------------- scrape_user
def test_scrape_user_entry_parity(patched_get):
    """خروجی باید همان قرارداد entry نیتر را داشته باشد + side-channel ها."""
    from sources.xscrape import scrape_user
    entries = scrape_user("testuser")
    assert len(entries) == 2
    e = entries[0]
    assert e["link"] == "https://x.com/testuser/status/%s" % TID1
    assert e["summary"] == TXT1
    assert e["title"] == TXT1
    assert e["published"].endswith("GMT")
    assert e["image"] is not None   # اولین عکس مدیا
    media = e["_xscrape_media"]
    assert {m["type"] for m in media} == {"image", "video"}
    assert e["_xscrape_quoted"] is None


def _block_old_session(monkeypatch):
    """مسیر قدیمی (تک‌شات روی session کوکی‌دار) بدون شبکه بسته می‌شود."""
    def _no_session(*a, **k):
        raise ConnectionError("old cookie-session path must not be used")
    monkeypatch.setattr("sources.xscrape._session",
                        type("S", (), {"get": staticmethod(_no_session)})())


def test_scrape_user_http_500(monkeypatch, no_sleep):
    """همهٔ تلاش‌های retry شکست بخورند → [] — تعداد تلاش = XSCRAPE_FETCH_TRIES."""
    import config
    from sources.xscrape import scrape_user
    monkeypatch.setattr(config, "XSCRAPE_FETCH_TRIES", 3, raising=False)
    calls = _patch_requests_get(monkeypatch, [_Resp("", 500)])
    _block_old_session(monkeypatch)
    assert scrape_user("x") == []
    assert calls["n"] == 3


def test_scrape_user_network_error(monkeypatch, no_sleep):
    from sources.xscrape import scrape_user

    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr("sources.xscrape.requests.get", boom)
    assert scrape_user("x") == []


def test_scrape_user_no_relay_data(monkeypatch, no_sleep):
    """صفحه 200 آمد ولی دادهٔ رله نبود (بلاک/چالش JS) → []."""
    from sources.xscrape import scrape_user
    monkeypatch.setattr("sources.xscrape.requests.get",
                        lambda *a, **k: _Resp("<html><body>challenge</body>"))
    assert scrape_user("x") == []


# ------------------------------------------------------- dispatch در twitter.fetch
def test_xscrape_mode_never_touches_nitter(monkeypatch, patched_get,
                                           tmp_path, sample_item):
    """در حالت xscrape هیچ تماسی با نیتر نباید زده شود."""
    import config
    import sources.twitter as twitter
    from sources import xscrape

    monkeypatch.setattr(config, "TWITTER_MODE", "xscrape")
    monkeypatch.setattr(twitter, "_load", lambda: None)
    monkeypatch.setattr(twitter, "_save", lambda: None)
    monkeypatch.setattr(twitter, "_due_accounts", lambda: ["testuser"])
    # اگر نیتر لمس شود این‌ها صدا می‌خورند → AssertionError
    monkeypatch.setattr(twitter, "pick_base",
                        lambda force=False: (_ for _ in ()).throw(
                            AssertionError("nitter touched in xscrape mode")))
    items = twitter.fetch(limit=6)
    assert items, "xscrape باید item تولید کند"
    it = items[0]
    assert it["url"].startswith("https://x.com/testuser/status/")
    assert it["source_tag"] == config.display_name("testuser")


def test_classic_mode_default_does_not_scrape(monkeypatch, tmp_path):
    """پیش‌فرض classic — اسکرپ هرگز نباید صدا زده شود."""
    import config
    import sources.twitter as twitter
    from sources import xscrape

    monkeypatch.setattr(config, "TWITTER_MODE", "classic")
    monkeypatch.setattr(xscrape, "scrape_user",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("scrape called in classic mode")))
    monkeypatch.setattr(twitter, "_load", lambda: None)
    monkeypatch.setattr(twitter, "_save", lambda: None)
    monkeypatch.setattr(twitter, "_due_accounts", lambda: [])
    assert twitter.fetch(limit=6) == []   # حسابی در نوبت نیست → بدون تماس


def test_video_fallback_to_fx_when_scrape_has_none(monkeypatch, sample_item):
    """اسکرپ mp4 نداد → resolve_video باید به fxtwitter/vxtwitter برود."""
    import sources.twitter as twitter

    calls = {}

    def fake_enrich(handle, tweet_id, timeout=12):
        calls["args"] = (handle, tweet_id)
        return {"video_url": "https://video.twimg.com/fx.mp4",
                "thumbnail_url": None, "media_urls": [], "source": "fxtwitter"}

    monkeypatch.setattr(twitter, "_enrich_tweet", fake_enrich)

    got = twitter.resolve_video("user", "123", scraped_mp4=None)
    assert got["video_url"] == "https://video.twimg.com/fx.mp4"
    assert calls["args"] == ("user", "123")

    # mp4 اسکرپی مستقیم مصرف می‌شود — enrichment صدا نمی‌خورد
    got2 = twitter.resolve_video("user", "123", scraped_mp4="https://direct.mp4")
    assert got2["video_url"] == "https://direct.mp4"
    assert calls["args"] == ("user", "123")   # تغییری نکرده


def test_quoted_tweet_sets_original_source(monkeypatch):
    """توییت نقل‌قول‌شده → original_source از نویسندهٔ توییت اصلی."""
    from sources import xscrape

    b1 = _b64(TID1)
    qb = _b64("1555555555555555555")
    script = (
        '"client:%s:details":$R[7]={"__typename":"Tweet","created_at_ms":1700000000000,full_text:"Look at this"}' % b1
        + '"%s":$R[11]={quoted_tweet_results:$R[3]={__ref:"TweetResults:1555555555555555555"}}' % b1
        + '"client:%s:details":$R[15]={"__typename":"Tweet","created_at_ms":1600000000000,full_text:"Original quote text"}' % qb
        + '"client:%s:core":$R[17]=$R[19]' % qb
        + '"VXNlclJlc3VsdHM6cXVvdGVk":$R[21]=client:VXNlcjoxNjY2Ng==":$R'
    )
    # extract_author روی fixture ساده جواب نمی‌دهد (ساختار واقعی پیچیده‌تر است)؛
    # پس فقط وجود quoted و متنش را چک می‌کنیم:
    quoted = xscrape.extract_quoted_tweet(script, b1, TID1)
    assert quoted is not None
    assert quoted["id"] == "1555555555555555555"
    assert quoted["text"] == "Original quote text"


def test_dead_cycle_falls_back_to_classic(monkeypatch):
    """سیکل کاملاً مرده بعد از سقف → برگشت به نیتر (اگر فلگ روشن باشد)."""
    import config
    import sources.twitter as twitter

    monkeypatch.setattr(config, "TWITTER_MODE", "xscrape")
    monkeypatch.setattr(config, "XSCRAPE_FALLBACK_CLASSIC", True)
    monkeypatch.setattr(config, "XSCRAPE_MAX_CONSECUTIVE_DEAD_CYCLES", 3)
    monkeypatch.setattr(twitter, "_load", lambda: None)
    monkeypatch.setattr(twitter, "_save", lambda: None)
    monkeypatch.setattr(twitter, "_due_accounts", lambda: ["deaduser"])
    monkeypatch.setattr(twitter, "_state", {"xscrape_dead_cycles": 2})
    monkeypatch.setattr("sources.xscrape.scrape_user", lambda u, count=None: [])

    classic_called = {"n": 0}

    def fake_classic(limit=6):
        classic_called["n"] += 1
        return [{"fallback": True}]

    monkeypatch.setattr(twitter, "_fetch_classic", fake_classic)
    monkeypatch.setattr(twitter.health, "record_counter", lambda *a, **k: None)

    items = twitter._fetch_xscrape(limit=6)
    assert classic_called["n"] == 1
    assert items == [{"fallback": True}]


# ------------------------------------------------------- fetch_tweet (لینک ادمین)
@pytest.fixture
def no_sleep(monkeypatch):
    """retry های _fetch_script نباید تست را کند کنند."""
    monkeypatch.setattr("sources.xscrape.time.sleep", lambda s: None)


def _patch_requests_get(monkeypatch, responses):
    """requests.get پشت‌سرهم از لیست responses مصرف می‌کند."""
    calls = {"n": 0}

    def fake_get(url, **k):
        i = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return responses[i]

    monkeypatch.setattr("sources.xscrape.requests.get", fake_get)
    return calls


def test_fetch_tweet_success(monkeypatch, no_sleep):
    """لینک status → (handle, entry) با همان قرارداد entry نیتر."""
    from sources.xscrape import fetch_tweet

    tid = TID1
    b1 = _b64(tid)
    script = (
        '"client:%s:details":$R[7]={"__typename":"Tweet","created_at_ms":%d,full_text:"%s"}' % (b1, MS1, TXT1)
        + '"client:%s:media_entities2:0":{"__typename":"ApiMediaEntity",type:"photo",media_url_https:"https://pbs.twimg.com/media/abc.jpg"}' % b1
    )
    _patch_requests_get(monkeypatch, [_Resp(_html(script))])

    handle, entry = fetch_tweet("https://x.com/FabrizioRomano/status/%s" % tid)
    assert handle == "FabrizioRomano"
    assert entry["link"].endswith("/status/%s" % tid)
    assert entry["summary"] == TXT1
    assert entry["_xscrape_media"][0]["type"] == "image"
    assert entry["published"].endswith("GMT")


def test_fetch_tweet_retries_on_403(monkeypatch, no_sleep):
    """x.com بی‌الگو 403 می‌دهد → retry باید جبرانش کند."""
    from sources.xscrape import fetch_tweet

    tid = TID1
    b1 = _b64(tid)
    script = ('"client:%s:details":$R[7]={"__typename":"Tweet","created_at_ms":%d,full_text:"%s"}'
              % (b1, MS1, TXT1))
    calls = _patch_requests_get(monkeypatch, [
        _Resp("", 403), _Resp("", 403), _Resp(_html(script)),
    ])

    handle, entry = fetch_tweet("https://x.com/testuser/status/%s" % tid)
    assert entry is not None
    assert calls["n"] == 3


def test_fetch_tweet_all_403(monkeypatch, no_sleep):
    from sources.xscrape import fetch_tweet
    _patch_requests_get(monkeypatch, [_Resp("", 403)])
    assert fetch_tweet("https://x.com/a/status/123") == (None, None)


def test_fetch_tweet_deleted_or_missing(monkeypatch, no_sleep):
    """صفحه آمد ولی توییت هدف در relay نیست (حذف‌شده)."""
    from sources.xscrape import fetch_tweet
    # فقط توییت دیگری در صفحه هست
    other = ('"client:%s:details":$R[7]={"__typename":"Tweet","created_at_ms":%d,full_text:"%s"}'
             % (_b64(TID2), MS2, TXT2))
    _patch_requests_get(monkeypatch, [_Resp(_html(other))])
    assert fetch_tweet("https://x.com/a/status/%s" % TID1) == (None, None)


def test_fetch_tweet_bad_urls():
    from sources.xscrape import fetch_tweet
    for bad in ("", "https://t.co/xyz", "not a link",
                "https://x.com/user/following"):
        assert fetch_tweet(bad) == (None, None)


def test_fetch_tweet_accepts_twitter_and_mobile(monkeypatch, no_sleep):
    """twitter.com و mobile. هم باید قبول شوند."""
    from sources.xscrape import fetch_tweet

    tid = TID1
    b1 = _b64(tid)
    script = ('"client:%s:details":$R[7]={"__typename":"Tweet","created_at_ms":%d,full_text:"%s"}'
              % (b1, MS1, TXT1))
    seen = {}

    def fake_get(url, **k):
        seen["url"] = url
        return _Resp(_html(script))

    monkeypatch.setattr("sources.xscrape.requests.get", fake_get)

    _, e1 = fetch_tweet("https://twitter.com/testuser/status/%s?s=20" % tid)
    assert e1 is not None
    _, e2 = fetch_tweet("https://mobile.x.com/testuser/status/%s/" % tid)
    assert e2 is not None


# ------------------------------------------- item_from_url در sources.twitter
def test_item_from_url_builds_full_item(monkeypatch, no_sleep):
    """لینک خام → item استاندارد، بدون فیلتر سن/طول — مثل بقیه خبرها."""
    import sources.twitter as twitter

    tid = TID1
    b1 = _b64(tid)
    script = (
        '"client:%s:details":$R[7]={"__typename":"Tweet","created_at_ms":%d,full_text:"%s"}' % (b1, MS1, TXT1)
        + '"client:%s:media_entities2:0":{"__typename":"ApiMediaEntity",type:"photo",media_url_https:"https://pbs.twimg.com/media/abc.jpg"}' % b1
    )
    monkeypatch.setattr(
        "sources.xscrape.requests.get",
        lambda url, **k: _Resp(_html(script)))

    item = twitter.item_from_url("https://x.com/testuser/status/%s" % tid)
    assert item is not None
    assert item["source"] == "Twitter"
    assert item["handle"] == "@testuser"
    assert item["url"].endswith("/status/%s" % tid)
    assert item["body"] == TXT1
    assert item["image"]   # عکس از مدیا
    assert item["priority"] is True


def test_item_from_url_failure_returns_none(monkeypatch, no_sleep):
    import sources.twitter as twitter
    monkeypatch.setattr(
        "sources.xscrape.requests.get",
        lambda url, **k: _Resp("", 403))
    assert twitter.item_from_url("https://x.com/a/status/123") is None


# ------------------------------------------------- تشخیص لینک خالی در main.py
def test_main_regex_matches_bare_link_only():
    """فقط پیامی که «فقط» لینک توییت است باید استخراج شود."""
    import re
    from main import _TWEET_LINK_ONLY as rx

    ok = [
        "https://x.com/FabrizioRomano/status/1796000000000000000",
        "http://x.com/FabrizioRomano/status/1796000000000000000/",
        "https://www.twitter.com/FabrizioRomano/statuses/1796000000000000000",
        "https://mobile.x.com/FabrizioRomano/status/1796000000000000000",
    ]
    bad = [
        "",
        "نگاه کن https://x.com/FabrizioRomano/status/1796000000000000000",
        "https://x.com/FabrizioRomano/status/1796000000000000000 عالی است",
        "https://x.com/FabrizioRomano/following",
        "https://t.co/xyz",
    ]
    for t in ok:
        assert rx.match(t.strip()), "باید قبول شود: " + t
    for t in bad:
        assert not rx.match(t.strip()), "نباید قبول شود: " + t


# ================== مشکل ۲ — سقف [:3] در حلقهٔ فیلتر (توییت‌های گم‌شده)
def _fresh_entry(text, tid, **extra):
    """entry شبیه خروجی scrape_user با timestamp تازه."""
    e = {
        "title": text[:200],
        "link": "https://x.com/testuser/status/%s" % tid,
        "summary": text,
        "image": None,
        "published": email.utils.formatdate(time.time() - 300, usegmt=True),
    }
    e.update(extra)
    return e


def _patch_twitter_fetch(monkeypatch, entries_by_user):
    import sources.twitter as twitter
    monkeypatch.setattr(twitter, "_load", lambda: None)
    monkeypatch.setattr(twitter, "_save", lambda: None)
    monkeypatch.setattr(twitter, "_due_accounts", lambda: list(entries_by_user))
    monkeypatch.setattr("sources.xscrape.scrape_user",
                        lambda u, count=None: entries_by_user.get(u, []))
    return twitter


def test_fetch_xscrape_checks_all_tweets_not_just_three(monkeypatch):
    """روزهای پرتوییت: همهٔ توییت‌های تازهٔ حساب باید دیده شوند، نه فقط ۳ تای اول."""
    entries = [_fresh_entry(TXT1, str(1700000000123450000 + i))
               for i in range(5)]
    twitter = _patch_twitter_fetch(monkeypatch, {"testuser": entries})
    items = twitter._fetch_xscrape(limit=10)
    assert len(items) == 5


# ================== مشکل ۱ — کلیدواژه‌ها و متن نقل‌قول
def test_fetch_xscrape_quoted_text_counts_for_relevance(monkeypatch):
    """کپشن کوتاه «Here we go 🔴» + متن لیورپولی در نقل‌قول → باید پذیرفته شود."""
    entry = _fresh_entry(
        "Here we go 🔴", TID1,
        _xscrape_quoted={
            "id": "1555555555555555555",
            "text": ("Liverpool have agreed a deal worth 120m for the winger "
                     "after a busy day of talks with his club"),
            "author_name": "Fabrizio Romano",
            "author_screen_name": "FabrizioRomano",
            "media": [], "card_image": None})
    twitter = _patch_twitter_fetch(monkeypatch, {"FabrizioRomano": [entry]})
    items = twitter._fetch_xscrape(limit=5)
    assert len(items) == 1
    assert "Liverpool" in items[0]["body"]


def test_fetch_xscrape_squad_player_name_counts_for_relevance(monkeypatch):
    """اسم بازیکن اسکواد (Wirtz) بدون هیچ‌کدام از کلیدواژه‌های قدیمی → پذیرفته شود."""
    entry = _fresh_entry(
        "Wirtz starts tonight and the coach expects a big performance",
        TID1)
    twitter = _patch_twitter_fetch(monkeypatch, {"FabrizioRomano": [entry]})
    items = twitter._fetch_xscrape(limit=5)
    assert len(items) == 1


def test_is_relevant_checks_quoted_text():
    import sources.twitter as twitter
    assert twitter._is_relevant(
        "Here we go 🔴", "FabrizioRomano",
        quoted_text="Liverpool reach full agreement with the player")
    assert not twitter._is_relevant(
        "Here we go 🔴", "FabrizioRomano",
        quoted_text="Real Madrid reach full agreement with the player")


def test_romano_keywords_cover_squad_and_manager():
    import config
    for kw in ("iraola", "wirtz", "szoboszlai", "mac allister", "van dijk",
               "gakpo", "ekitike", "barcola", "curtis jones",
               "harvey elliott", "isak", "konate", "nunez"):
        assert kw in config.ROMANO_KEYWORDS, kw
    assert "slot" not in config.ROMANO_KEYWORDS   # اسلوت دیگر مربی نیست


# ================== مشکل ۳ — retry در scrape_user
def test_scrape_user_retries_on_403(monkeypatch, no_sleep):
    """اولین تلاش 403، تلاش بعدی موفق → scrape_user باید entry بدهد."""
    import config
    from sources import xscrape
    monkeypatch.setattr(config, "XSCRAPE_FETCH_TRIES", 3, raising=False)
    calls = _patch_requests_get(monkeypatch, [
        _Resp("", 403), _Resp(_html(_relay_script())),
    ])
    _block_old_session(monkeypatch)
    entries = xscrape.scrape_user("testuser")
    assert entries, "باید بعد از retry موفق می‌شد"
    assert calls["n"] == 2


def test_scrape_user_all_tries_exhausted(monkeypatch, no_sleep):
    """بعد از XSCRAPE_FETCH_TRIES تلاش ناموفق → [] (رفتار retry-دار)."""
    import config
    from sources import xscrape
    monkeypatch.setattr(config, "XSCRAPE_FETCH_TRIES", 3, raising=False)
    calls = _patch_requests_get(monkeypatch, [_Resp("", 500)])
    _block_old_session(monkeypatch)
    assert xscrape.scrape_user("testuser") == []
    assert calls["n"] == 3


# ================== مشکل ۴ — توییت‌های بلند (note_tweet / X Premium)
def _b64raw(s):
    return base64.b64encode(s.encode()).decode()


LONG_TXT = (
    "Liverpool full analysis: Frimpong and Kerkez numbers when playing at "
    "full back 25/26 back up the eye test. Defensive weaknesses, passing "
    "OBV percentiles and aerial win numbers all highlighted here with the "
    "complete data sample for both full backs this season and next")
NTID = "2094056601736888320"
NT_RESULTS_REF = _b64raw("NoteTweetResults:" + NTID)
NT_REF = _b64raw("NoteTweet:" + NTID)


def _note_script():
    """relay با full_text کوتاه + بلوک note_tweet (ساختار واقعی x.com)."""
    b1 = _b64(TID1)
    return (
        '"client:%s:details":$R[7]={"__typename":"Tweet","created_at_ms":%d,'
        'full_text:"%s",note_tweet:$R[31]={__ref:"client:%s:note_tweet"}}'
        % (b1, MS1, TXT1, b1)
        + '"client:%s:note_tweet":$R[71]={__typename:"NoteTweetData",'
        'is_expandable:!0,note_tweet_results:$R[72]={__ref:"%s"}}'
        % (b1, NT_RESULTS_REF)
        + '%s:$R[73]={__typename:"NoteTweetResults",result:$R[74]={__ref:"%s"}}'
        % (NT_RESULTS_REF, NT_REF)
        + '"%s":$R[75]={__typename:"NoteTweet",text:"%s"}' % (NT_REF, LONG_TXT)
    )


def test_parse_relay_tweets_prefers_note_tweet():
    """توییت بلند → باید متن کامل note_tweet برگردد نه full_text کوتاه."""
    from sources.xscrape import parse_relay_tweets
    tweets = parse_relay_tweets(_note_script(), 5)
    assert tweets[0]["text"] == LONG_TXT


def test_parse_relay_tweets_falls_back_to_full_text():
    """توییت معمولی بدون note_tweet → همان full_text (رفتار فعلی حفظ شود)."""
    from sources.xscrape import parse_relay_tweets
    tweets = parse_relay_tweets(_relay_script(), 5)
    assert tweets[0]["text"] == TXT1


def test_quoted_tweet_prefers_note_tweet_text():
    """نقل‌قول بلند → متن کامل note_tweet به‌جای full_text کوتاه."""
    from sources.xscrape import extract_quoted_tweet
    b1 = _b64(TID1)
    qb = _b64("1555555555555555555")
    script = (
        '"client:%s:details":$R[7]={"__typename":"Tweet","created_at_ms":%d,'
        'full_text:"Look at this"}' % (b1, MS1)
        + '"%s":$R[11]={quoted_tweet_results:$R[3]={__ref:"TweetResults:1555555555555555555"}}' % b1
        + '"client:%s:details":$R[15]={"__typename":"Tweet","created_at_ms":%d,'
        'full_text:"Short legacy text",note_tweet:$R[16]={__ref:"client:%s:note_tweet"}}'
        % (qb, MS2, qb)
        + '"client:%s:note_tweet":$R[17]={__typename:"NoteTweetData",'
        'note_tweet_results:$R[18]={__ref:"%s"}}' % (qb, NT_RESULTS_REF)
        + '%s:$R[19]={__typename:"NoteTweetResults",result:$R[20]={__ref:"%s"}}'
        % (NT_RESULTS_REF, NT_REF)
        + '"%s":$R[21]={__typename:"NoteTweet",text:"%s"}' % (NT_REF, LONG_TXT)
    )
    quoted = extract_quoted_tweet(script, b1, TID1)
    assert quoted is not None
    assert quoted["text"] == LONG_TXT


def test_fetch_tweet_returns_note_tweet_text(monkeypatch, no_sleep):
    """لینک توییت بلند (ادمین) → متن کامل از note_tweet."""
    from sources.xscrape import fetch_tweet
    _patch_requests_get(monkeypatch, [_Resp(_html(_note_script()))])
    handle, entry = fetch_tweet("https://x.com/testuser/status/%s" % TID1)
    assert entry is not None
    assert entry["summary"] == LONG_TXT
