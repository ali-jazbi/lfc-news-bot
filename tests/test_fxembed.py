"""تست‌های منبع FxEmbed / FxTwitter API v2 (حالت TWITTER_MODE=fxembed).

کاملاً بدون شبکه: پاسخ‌های API به‌صورت fixture سینتتیک ساخته می‌شوند و
requests.get ماک می‌شود. ساختار fixtureها از پاسخ واقعی api.fxtwitter.com
کپی شده (id/url/text/created_timestamp/media.all/media.videos/quote).
"""
import json
import time

import pytest

TID1 = "2104026026506403964"
TID2 = "2104026019589951488"
TID3 = "2104026019589951400"

TS1 = int(time.time()) - 600            # ۱۰ دقیقه پیش
TS2 = int(time.time()) - 7200           # ۲ ساعت پیش

# متن‌ها باید از فیلترهای واقعی (کلیدواژه + حداقل طول/کلمه) رد شوند
TXT1 = ("Liverpool have opened talks with the representatives of a new midfielder "
        "and the negotiations are expected to continue in the coming days")
TXT2 = ("The reds are set to confirm the deal for a new defender after medical "
        "tests were completed at the training ground this morning")

PHOTO = {"type": "photo", "id": "1", "url": "https://pbs.twimg.com/media/aaa.jpg?name=orig",
         "width": 1200, "height": 800}
PHOTO2 = {"type": "photo", "id": "2", "url": "https://pbs.twimg.com/media/bbb.jpg?name=orig"}
VIDEO = {
    "type": "video", "id": "3",
    "url": "https://video.twimg.com/amplify_video/9/vid/avc1/1080x1920/high.mp4?tag=29",
    "thumbnail_url": "https://pbs.twimg.com/amplify_video_thumb/9/img/t.jpg",
    "duration": 12.5, "width": 1080, "height": 1920,
    "formats": [
        {"url": "https://video.twimg.com/pl/9.m3u8?tag=29", "container": "m3u8"},
        {"url": "https://video.twimg.com/9/320.mp4?tag=29", "container": "mp4",
         "bitrate": 632000, "codec": "h264"},
        {"url": "https://video.twimg.com/9/720.mp4?tag=29", "container": "mp4",
         "bitrate": 2176000, "codec": "h264"},
    ],
}


def _status(**over):
    """یک status واقعی‌نما (کلیدها عیناً همان API)."""
    st = {
        "type": "status",
        "id": TID1,
        "url": "https://x.com/FabrizioRomano/status/" + TID1,
        "text": TXT1,
        "created_at": "Sun Sep 27 01:51:10 +0000 2026",
        "created_timestamp": TS1,
        "is_note_tweet": False,
        "lang": "en",
        "author": {"screen_name": "FabrizioRomano", "name": "Fabrizio Romano"},
    }
    st.update(over)
    return st


def _quote(**over):
    q = {
        "type": "status",
        "id": TID3,
        "url": "https://x.com/DAZNFootball/status/" + TID3,
        "text": "Big moves happening in North London",
        "author": {"screen_name": "DAZNFootball", "name": "DAZN Football"},
    }
    q.update(over)
    return q


class _Resp:
    """پاسخ fake — مثل requests.Response فقط status_code/json/text دارد."""

    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


def _page(results, code=200, cursor=None):
    return {"code": code, "results": list(results),
            "cursor": cursor or {"top": "T", "bottom": "B"}}


def _patch(monkeypatch, responses):
    """requests.get ماژول fxembed را با لیست پاسخ‌ها جایگزین می‌کند.

    خروجی: لیست فراخوانی‌ها ({url, params}) تا پارامترها هم قابل بررسی باشند.
    """
    calls = []
    seq = list(responses)

    def fake_get(url, params=None, timeout=None, headers=None, **kw):
        calls.append({"url": url, "params": dict(params or {})})
        if not seq:
            return _Resp(_page([]))
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("sources.fxembed.requests.get", fake_get)
    return calls


@pytest.fixture
def no_sleep(monkeypatch):
    """backoff بین retry ها نباید تست را کند کند."""
# ==================================================== قرارداد entry (پایه)
def test_scrape_user_returns_entry_contract(monkeypatch, no_sleep):
    """خروجی باید همان قرارداد entry نیتر/xscrape باشد (پایپ‌لاین دست نخورد)."""
    from sources import fxembed
    _patch(monkeypatch, [_Resp(_page([_status()]))])
    entries = fxembed.scrape_user("FabrizioRomano")
    assert len(entries) == 1
    e = entries[0]
    assert {"title", "link", "summary", "image", "published",
            "_xscrape_media", "_xscrape_quoted"} <= set(e)
    assert e["link"] == "https://x.com/FabrizioRomano/status/" + TID1
    assert e["summary"] == TXT1
    assert e["title"] == TXT1[:200]


def test_published_is_rfc822_parseable(monkeypatch, no_sleep):
    """published باید برای tweet_age_hours() (RFC822) قابل خواندن باشد."""
    from sources import fxembed
    from sources import twitter
    _patch(monkeypatch, [_Resp(_page([_status()]))])
    e = fxembed.scrape_user("FabrizioRomano")[0]
    assert e["published"].endswith("GMT")
    age = twitter.tweet_age_hours(e)
    assert age is not None and 0 <= age < 1        # ۱۰ دقیقه پیش


def test_no_media_gives_none_image(monkeypatch, no_sleep):
    from sources import fxembed
    _patch(monkeypatch, [_Resp(_page([_status(media=None)]))])
    e = fxembed.scrape_user("FabrizioRomano")[0]
    assert e["image"] is None
    assert e["_xscrape_media"] == []
    assert e["_xscrape_quoted"] is None


# ===================================================================== media
def test_media_photos_and_video_mapped(monkeypatch, no_sleep):
    """عکس‌ها + ویدیو (بهترین mp4) → همان شکل _xscrape_media که xscrape می‌دهد."""
    from sources import fxembed
    media = {"all": [dict(PHOTO), dict(VIDEO), dict(PHOTO2)], "videos": [dict(VIDEO)]}
    _patch(monkeypatch, [_Resp(_page([_status(media=media)]))])
    e = fxembed.scrape_user("FabrizioRomano")[0]
    kinds = [m["type"] for m in e["_xscrape_media"]]
    assert kinds == ["image", "video", "image"]
    assert e["_xscrape_media"][0]["url"] == PHOTO["url"]
    assert e["image"] == PHOTO["url"]                       # اولین عکس
    assert e["_xscrape_media"][1]["url"] == VIDEO["url"]     # mp4 با کیفیت بالا


def test_video_picks_best_mp4_from_formats(monkeypatch, no_sleep):
    """اگر url خودش m3u8 بود، بالاترین bitrate از formats انتخاب شود."""
    from sources import fxembed
    v = dict(VIDEO)
    v["url"] = "https://video.twimg.com/pl/9.m3u8?tag=29"
    _patch(monkeypatch, [_Resp(_page([_status(media={"all": [v]})]))])
    e = fxembed.scrape_user("FabrizioRomano")[0]
    assert e["_xscrape_media"] == [
        {"type": "video", "url": "https://video.twimg.com/9/720.mp4?tag=29"}]


def test_video_without_mp4_falls_back_to_thumbnail(monkeypatch, no_sleep):
    """ویدیوی بدون mp4 (فقط m3u8) → پوستر، نه از دست رفتن تصویر توییت."""
    from sources import fxembed
    v = {"type": "video", "url": "https://video.twimg.com/pl/9.m3u8",
         "thumbnail_url": "https://pbs.twimg.com/amplify_video_thumb/9/img/t.jpg",
         "formats": [{"url": "https://video.twimg.com/pl/9.m3u8", "container": "m3u8"}]}
    _patch(monkeypatch, [_Resp(_page([_status(media={"all": [v]})]))])
    e = fxembed.scrape_user("FabrizioRomano")[0]
    assert e["_xscrape_media"] == [{"type": "image", "url": v["thumbnail_url"]}]
    assert e["image"] == v["thumbnail_url"]


def test_media_duplicates_removed(monkeypatch, no_sleep):
    from sources import fxembed
    media = {"all": [dict(PHOTO), dict(PHOTO)]}
    _patch(monkeypatch, [_Resp(_page([_status(media=media)]))])
    e = fxembed.scrape_user("FabrizioRomano")[0]
    assert len(e["_xscrape_media"]) == 1


# ===================================================================== quote
def test_quoted_tweet_contract(monkeypatch, no_sleep):
    """کلیدهای quote باید همان چیزی باشد که build_tweet_item استفاده می‌کند."""
    from sources import fxembed
    _patch(monkeypatch, [_Resp(_page([_status(quote=_quote())]))])
    e = fxembed.scrape_user("FabrizioRomano")[0]
    q = e["_xscrape_quoted"]
    assert q["text"] == "Big moves happening in North London"
    assert q["author_screen_name"] == "DAZNFootball"
    assert q["author_name"] == "DAZN Football"
    assert q["id"] == TID3
    monkeypatch.setattr("sources.fxembed.time.sleep", lambda s: None)
# ============================================ ۴۰۴ → with_replies + فیلترها
NOT_FOUND = _Resp({"code": 404, "message": "User not found or empty timeline"}, 404)


def test_statuses_404_falls_back_to_with_replies(monkeypatch, no_sleep):
    """timeline خالی (404) → تلاش با with_replies و فیلتر به توییت‌های خودِ حساب."""
    from sources import fxembed
    other = _status(id=TID2, author={"screen_name": "TaintlessRed", "name": "T"},
                    text=TXT2, replying_to={"screen_name": "LiverpoolFF"})
    own = _status(id=TID1, author={"screen_name": "LiverpoolFF", "name": "LFF"},
                  url="https://x.com/LiverpoolFF/status/" + TID1, text=TXT1)
    own_reply = _status(id="190", author={"screen_name": "LiverpoolFF", "name": "LFF"},
                        text=TXT2, replying_to={"screen_name": "TaintlessRed"})
    retweet = _status(id="191", author={"screen_name": "Davolaar", "name": "D"},
                      url="https://x.com/Davolaar/status/191",
                      reposted_by={"screen_name": "LiverpoolFF"}, text=TXT2)
    calls = _patch(monkeypatch, [
        NOT_FOUND,
        _Resp(_page([other, own, own_reply, retweet])),
    ])
    entries = fxembed.scrape_user("LiverpoolFF")
    assert len(calls) == 2
    assert "with_replies" not in calls[0]["params"]
    assert calls[1]["params"]["with_replies"] == "1"
    # فقط توییت خودش + ریتوییت خودش (ریپلای و توییت دیگران رد می‌شوند)
    assert [e["link"].split("/")[-1] for e in entries] == [TID1, "191"]


def test_primary_path_keeps_own_replies(monkeypatch, no_sleep):
    """در مسیر اصلی ریپلای‌ها فیلتر نمی‌شوند (توییت‌های رشته‌ای/X thread)."""
    from sources import fxembed
    own_reply = _status(replying_to={"screen_name": "FabrizioRomano"})
    _patch(monkeypatch, [_Resp(_page([own_reply]))])
    assert len(fxembed.scrape_user("FabrizioRomano")) == 1


def test_suspended_account_returns_empty(monkeypatch, no_sleep):
    """حساب ساسپند: هر دو مسیر ۴۰۴ → [] (بدون exception، بدون حلقه)."""
    from sources import fxembed
    calls = _patch(monkeypatch, [NOT_FOUND, NOT_FOUND])
    assert fxembed.scrape_user("AnfieldSector") == []
    assert len(calls) == 2


def test_no_with_replies_retry_when_page_ok_but_empty(monkeypatch, no_sleep):
    """صفحه‌ی سالم ولی خالی (۲۰۰) → دوباره‌خوانی بی‌فایده نکن."""
    from sources import fxembed
    calls = _patch(monkeypatch, [_Resp(_page([]))])
    assert fxembed.scrape_user("FabrizioRomano") == []
    assert len(calls) == 1


# ============================================ incremental polling (since/204)
def test_since_param_is_sent(monkeypatch, no_sleep):
    from sources import fxembed
    calls = _patch(monkeypatch, [_Resp(_page([_status()]))])
    fxembed.scrape_user("FabrizioRomano", since=1790473870)
    assert calls[0]["params"]["since"] == 1790473870


def test_204_means_nothing_new(monkeypatch, no_sleep):
    """204 = هیچ پست تازه‌تری نیست → [] و تلاش دوم (with_replies) هم نکن."""
    from sources import fxembed
    calls = _patch(monkeypatch, [_Resp(None, 204)])
    assert fxembed.scrape_user("FabrizioRomano", since=1) == []
    assert len(calls) == 1


def test_count_is_capped_and_sent(monkeypatch, no_sleep):
    from sources import fxembed
    many = [_status(id=str(2104026026506403964 + i)) for i in range(30)]
    calls = _patch(monkeypatch, [_Resp(_page(many))])
    entries = fxembed.scrape_user("FabrizioRomano", count=5)
    assert calls[0]["params"]["count"] == 5
    assert len(entries) == 5


# ================================================================== خطاها
def test_network_error_never_raises(monkeypatch, no_sleep):
    """شبکه مرده (SSL/Connection) → [] بعد از چند تلاش، بدون exception."""
    import requests
    from sources import fxembed
    err = requests.exceptions.ConnectionError("boom")
    calls = _patch(monkeypatch, [err, err, err])
    assert fxembed.scrape_user("FabrizioRomano") == []
    assert len(calls) == 3                          # تلاش‌ها = FXEMBED_FETCH_TRIES


def test_bad_json_never_raises(monkeypatch, no_sleep):
    from sources import fxembed
    _patch(monkeypatch, [_Resp(None, 200)])
    assert fxembed.scrape_user("FabrizioRomano") == []

# ============================== pagination واقعی (بازپخشِ backlog در polling)
def _statuses(*ids, **over):
    out = [_status(id=i, url="https://x.com/FabrizioRomano/status/" + i,
                   text=TXT1, created_timestamp=TS1) for i in ids]
    return out


def test_pagination_follows_cursor_when_since_used(monkeypatch, no_sleep):
    """با since: اگر backlog از یک صفحه بیشتر باشد صفحه‌ی دوم هم خوانده می‌شود.

    ریسک اصلی: ۲۰ پست در پنجره‌ی polling → بدون cursor بقیه‌ی خبرها گم می‌شوند.
    """
    from sources import fxembed
    ids1 = ["21040260265064039%02d" % i for i in range(20)]
    ids2 = ["21040260265064038%02d" % i for i in range(5)]
    calls = _patch(monkeypatch, [
        _Resp(_page(_statuses(*ids1), cursor={"top": "T", "bottom": "C1"})),
        _Resp(_page(_statuses(*ids2), cursor={"top": "C1", "bottom": "C2"})),
        _Resp(_page([])),
    ])
    entries = fxembed.scrape_user("FabrizioRomano", since=TS1 - 900)
    assert len(entries) == 25
    assert len(calls) == 3
    # صفحه‌های بعدی فقط cursor دارند (مستندات: since فقط بدون cursor معتبر است)
    assert calls[1]["params"]["cursor"] == "C1"
    assert "since" not in calls[1]["params"]
    assert calls[2]["params"]["cursor"] == "C2"
    assert "since" not in calls[2]["params"]
    links = [e["link"].split("/")[-1] for e in entries]
    assert links[0] == ids1[0] and ids1[-1] in links and len(set(links)) == 25


def test_pagination_deduplicates_overlap(monkeypatch, no_sleep):
    """اگر دو صفحه یک id داشته باشند، فقط یکی وارد لیست می‌شود."""
    from sources import fxembed
    a = ["2104026026506403%03d" % i for i in range(20)]
    _patch(monkeypatch, [
        _Resp(_page(_statuses(*a), cursor={"top": "T", "bottom": "C1"})),
        _Resp(_page(_statuses(a[0], a[1], "2104026026506390001"))),
        _Resp(_page([])),
    ])
    entries = fxembed.scrape_user("FabrizioRomano", since=1)
    links = [e["link"].split("/")[-1] for e in entries]
    # ۲۰ تای صفحه‌ی اول + ۱ تای جدید صفحه‌ی دوم (۲ id تکراری حذف می‌شوند)
    assert len(links) == len(set(links)) == 21


def test_pagination_respects_max_pages(monkeypatch, no_sleep):
    """سقف صفحه‌ها (FXEMBED_MAX_PAGES) جلوی حلقه‌ی بی‌نهایت را می‌گیرد."""
    import config
    from sources import fxembed
    monkeypatch.setattr(config, "FXEMBED_MAX_PAGES", 2)
    calls = _patch(monkeypatch, [
        _Resp(_page(_statuses("1", "2"), cursor={"top": "T", "bottom": "C1"})),
        _Resp(_page(_statuses("3", "4"), cursor={"top": "C1", "bottom": "C2"})),
        _Resp(_page(_statuses("5"))),
    ])
    entries = fxembed.scrape_user("FabrizioRomano", since=1)
    assert len(calls) == 2                    # صفحه‌ی سوم رزرو شد
    assert len(entries) == 4


def test_no_pagination_without_since(monkeypatch, no_sleep):
    """polling عادی (بدون since) فقط صفحه‌ی اول می‌خواند."""
    from sources import fxembed
    calls = _patch(monkeypatch, [
        _Resp(_page(_statuses("1", "2"), cursor={"top": "T", "bottom": "C1"})),
    ])
    entries = fxembed.scrape_user("FabrizioRomano")
    assert len(calls) == 1
    assert len(entries) == 2


# ============================== suspended / not-found (cooldown طولانی)
def test_suspension_reason_detects_suspended(monkeypatch, no_sleep):
    from sources import fxembed
    _patch(monkeypatch, [_Resp({"code": 404, "message": "User is suspended"})])
    assert fxembed.suspension_reason("AnfieldSector") == "suspended"


def test_suspension_reason_detects_not_found(monkeypatch, no_sleep):
    from sources import fxembed
    _patch(monkeypatch, [_Resp({"code": 404, "message": "User not found"})])
    assert fxembed.suspension_reason("ghostuser") == "not_found"


def test_suspension_reason_none_for_healthy_account(monkeypatch, no_sleep):
    from sources import fxembed
    _patch(monkeypatch, [_Resp({"code": 200, "user": {"screen_name": "LFC"}})])
    assert fxembed.suspension_reason("LFC") is None


# ============================== partial failure (بخشی موفق، بخشی ناموفق)
def test_partial_failure_updates_state_only_for_successes(monkeypatch):
    """حساب ناموفق نباید since بگیرد و نباید dead-cycle ثبت کند."""
    fxembed, twitter = _fx_mode(monkeypatch, accounts=("FabrizioRomano", "LFC"))

    def fake_scrape(u, count=None, since=None):
        return [] if u == "LFC" else [_entry()]

    monkeypatch.setattr(fxembed, "scrape_user", fake_scrape)
    monkeypatch.setattr(fxembed, "suspension_reason", lambda u: None)
    counters = []
    monkeypatch.setattr(twitter.health, "record_counter",
                        lambda name, n=1: counters.append(name))

    items = twitter.fetch(limit=10)
    assert len(items) == 1                  # خبرهای موفق وارد پایپ‌لاین شدند
    assert "fxembed_dead_cycle" not in counters
    since_map = twitter._state["fxembed_since"]
    assert "fabrizioromano" in since_map
    assert "lfc" not in since_map           # state فقط برای موفق‌ها


def test_failed_account_retried_next_cycle(monkeypatch):
    """حساب ناموفق سیکل بعد باید دوباره کامل خوانده شود (since=None)."""
    fxembed, twitter = _fx_mode(monkeypatch, accounts=("FabrizioRomano", "LFC"))
    seen = {}
    ok = {"lfc": False}

    def fake_scrape(u, count=None, since=None):
        seen.setdefault(u, []).append(since)
        if u == "LFC" and not ok["lfc"]:
            return []
        return [_entry()]

    monkeypatch.setattr(fxembed, "scrape_user", fake_scrape)
    monkeypatch.setattr(fxembed, "suspension_reason", lambda u: None)
    twitter.fetch(limit=10)
    assert seen["LFC"] == [None]
    ok["lfc"] = True
    twitter.fetch(limit=10)
    assert seen["LFC"][1] is None           # دوباره بدون since → retry واقعی


def test_suspended_account_gets_24h_cooldown_and_is_skipped(monkeypatch):
    """حساب suspended: یک بار تشخیص، بعد تا ۲۴ ساعت اصلاً درخواست نمی‌رود."""
    import time as _t

    import config
    fxembed, twitter = _fx_mode(monkeypatch,
                                accounts=("FabrizioRomano", "AnfieldSector"))
    calls = []

    def fake_scrape(u, count=None, since=None):
        calls.append(u)
        return [] if u == "AnfieldSector" else [_entry()]

    monkeypatch.setattr(config, "FXEMBED_SUSPENDED_COOLDOWN", 86400)
    monkeypatch.setattr(fxembed, "scrape_user", fake_scrape)
    monkeypatch.setattr(fxembed, "suspension_reason",
                        lambda u: "suspended" if u == "AnfieldSector" else None)

    twitter.fetch(limit=10)
    cd = twitter._state["fxembed_cooldown"]["anfieldsector"]
    assert cd["reason"] == "suspended"
    assert cd["until"] > _t.time() + 3600
    assert "AnfieldSector" in calls         # سیکل اول = کشف (یک بار)

    calls.clear()
    twitter.fetch(limit=10)                   # سیکل بعد: باید کاملاً skip شود
    assert "AnfieldSector" not in calls
    assert "FabrizioRomano" in calls


def test_cooldown_expires_after_24h(monkeypatch):
    """بعد از گذشت مهلت، حساب دوباره بررسی می‌شود."""
    fxembed, twitter = _fx_mode(monkeypatch, accounts=("AnfieldSector",))
    monkeypatch.setattr(fxembed, "suspension_reason", lambda u: "suspended")
    twitter._state["fxembed_cooldown"] = {"anfieldsector": {
        "until": 1.0, "reason": "suspended"}}
    calls = []
    monkeypatch.setattr(fxembed, "scrape_user",
                        lambda u, count=None, since=None: calls.append(u) or [])
    twitter.fetch(limit=10)
    assert calls == ["AnfieldSector"]


def test_fxembed_never_sleeps_between_accounts(monkeypatch):
    """Throttle واقعی = تعداد worker است، نه sleep بعد از submit همه."""
    fxembed, twitter = _fx_mode(monkeypatch)

    def boom(_):
        raise AssertionError("fetch نباید sleep کند — درخواست‌ها از قبل submit شده‌اند")

    monkeypatch.setattr(twitter.time, "sleep", boom)
    monkeypatch.setattr(fxembed, "scrape_user",
                        lambda u, count=None, since=None: [_entry()])
    monkeypatch.setattr(fxembed, "suspension_reason", lambda u: None)
    assert len(twitter.fetch(limit=10)) == 1


# ============================================================ thread / focus
def test_grouped_thread_uses_focal_status(monkeypatch, no_sleep):
    """اگر پاسخ thread بود (groupthreads)، status کانونی همان توییت است."""
    from sources import fxembed
    thread = {"type": "thread", "code": 200, "status": _status(),
              "thread": [_status(id=TID2)]}
    _patch(monkeypatch, [_Resp(_page([thread]))])
    entries = fxembed.scrape_user("FabrizioRomano")
    assert len(entries) == 1
    assert entries[0]["link"].endswith(TID1)


# ============================================== fetch_tweet (لینک ادمین)
def test_fetch_tweet_by_url(monkeypatch, no_sleep):
    from sources import fxembed
    calls = _patch(monkeypatch, [_Resp({"code": 200, "status": _status()})])
    handle, entry = fxembed.fetch_tweet(
        "https://x.com/FabrizioRomano/status/" + TID1)
    assert handle == "FabrizioRomano"
    assert entry["summary"] == TXT1
    assert entry["link"].endswith(TID1)
    assert "/2/status/" + TID1 in calls[0]["url"]


def test_fetch_tweet_invalid_url_no_network(monkeypatch, no_sleep):
    from sources import fxembed
    calls = _patch(monkeypatch, [_Resp({"code": 200})])
    assert fxembed.fetch_tweet("https://example.com/not-a-tweet") == (None, None)
    assert calls == []


# ============================== یکپارچگی با twitter.py (بدون شبکه)
def _entry(link_tid=TID1, text=TXT1, ts=TS1, media=None, quoted=None):
    """entry با همان قرارداد، مثل چیزی که fxembed.scrape_user می‌دهد."""
    import email.utils
    return {
        "title": text[:200],
        "link": "https://x.com/FabrizioRomano/status/" + link_tid,
        "summary": text,
        "image": (media or [{}])[0].get("url"),
        "published": email.utils.formatdate(ts, usegmt=True),
        "_xscrape_media": media or [],
        "_xscrape_quoted": quoted,
    }


def _fx_mode(monkeypatch, accounts=("FabrizioRomano",)):
    """twitter را در حالت fxembed با تنظیمات قابل پیش‌بینی آماده می‌کند."""
    import config
    from sources import fxembed, twitter
    monkeypatch.setattr(config, "TWITTER_MODE", "fxembed")
    monkeypatch.setattr(config, "ROMANO_KEYWORDS", ["liverpool"])
    monkeypatch.setattr(config, "TWITTER_LFC_ONLY", [])
    monkeypatch.setattr(config, "TWEET_MAX_AGE_HOURS", 24)
    monkeypatch.setattr(twitter, "_load", lambda: None)
    monkeypatch.setattr(twitter, "_save", lambda: None)
    monkeypatch.setattr(twitter, "_due_accounts", lambda: list(accounts))
    monkeypatch.setattr(twitter, "_state", {})
    monkeypatch.setattr(twitter.health, "record_counter", lambda *a, **k: None)
    return fxembed, twitter


def test_fetch_dispatches_to_fxembed(monkeypatch):
    """TWITTER_MODE=fxembed باید از fxembed بخواند و item کامل بسازد."""
    fxembed, twitter = _fx_mode(monkeypatch)
    seen = {}

    def fake_scrape(u, count=None, since=None):
        seen["args"] = (u, count, since)
        return [_entry(media=[{"type": "image", "url": PHOTO["url"]},
                              {"type": "video", "url": "https://video.twimg.com/x.mp4"}])]

    monkeypatch.setattr(fxembed, "scrape_user", fake_scrape)
    items = twitter.fetch(limit=5)
    assert seen["args"][0] == "FabrizioRomano"
    assert len(items) == 1
    item = items[0]
    assert item["source"] == "Twitter"
    assert item["handle"] == "@FabrizioRomano"
    assert item["url"].endswith(TID1)
    assert item["image"] == PHOTO["url"]
    assert item["images"] == [PHOTO["url"]]
    assert item["video_urls"] == ["https://video.twimg.com/x.mp4"]
    assert item["video_url"] == "https://video.twimg.com/x.mp4"


def test_fxembed_mode_still_applies_filters(monkeypatch):
    """فیلترهای موجود (کلیدواژه/سن/نویز) در حالت fxembed هم اعمال می‌شوند."""
    fxembed, twitter = _fx_mode(monkeypatch)
    irrelevant = _entry(text=("What a lovely evening in Milano with friends "
                              "and a very nice dinner downtown tonight"))
    monkeypatch.setattr(fxembed, "scrape_user",
                        lambda u, count=None, since=None: [irrelevant])
    assert twitter.fetch(limit=5) == []


def test_fxembed_records_last_seen_and_sends_since(monkeypatch):
    """incremental polling: تایم‌استمپ آخرین توییت ذخیره و در سیکل بعد فرستاده شود."""
    import config
    fxembed, twitter = _fx_mode(monkeypatch)
    monkeypatch.setattr(config, "FXEMBED_USE_SINCE", True)
    monkeypatch.setattr(config, "FXEMBED_SINCE_OVERLAP_SECONDS", 900)
    seen = {}

    def fake_scrape(u, count=None, since=None):
        seen["since"] = since
        return [_entry()]

    monkeypatch.setattr(fxembed, "scrape_user", fake_scrape)
    twitter.fetch(limit=5)
    assert twitter._state["fxembed_since"]["fabrizioromano"] == TS1

    twitter.fetch(limit=5)                     # سیکل بعد
    assert seen["since"] == TS1 - 900          # با حاشیه‌ی اطمینان


def test_fxembed_since_disabled_sends_none(monkeypatch):
    import config
    fxembed, twitter = _fx_mode(monkeypatch)
    monkeypatch.setattr(config, "FXEMBED_USE_SINCE", False)
    seen = {}

    def fake_scrape(u, count=None, since=None):
        seen["since"] = since
        return [_entry()]

    monkeypatch.setattr(fxembed, "scrape_user", fake_scrape)
    twitter.fetch(limit=5)
    assert seen["since"] is None


def test_fxembed_dead_cycle_is_counted_and_no_nitter(monkeypatch):
    """حالت fxembed عمداً به نیتر fallback نمی‌کند (نیتر دیگر قابل اتکا نیست)."""
    fxembed, twitter = _fx_mode(monkeypatch)
    monkeypatch.setattr(fxembed, "scrape_user", lambda u, count=None, since=None: [])
    counters = []
    monkeypatch.setattr(twitter.health, "record_counter",
                        lambda name, n=1: counters.append(name))
    called = {"classic": 0}

    def fake_classic(limit=6):
        called["classic"] += 1
        return []

    monkeypatch.setattr(twitter, "_fetch_classic", fake_classic)
    assert twitter.fetch(limit=5) == []
    assert "fxembed_dead_cycle" in counters
    assert called["classic"] == 0


# ------------------------------------- لینک توییت ادمین در هر دو حالت
def test_item_from_url_uses_fxembed_in_fxembed_mode(monkeypatch):
    import config
    from sources import fxembed, twitter
    monkeypatch.setattr(config, "TWITTER_MODE", "fxembed")
    monkeypatch.setattr(fxembed, "fetch_tweet",
                        lambda url: ("FabrizioRomano", _entry()))
    item = twitter.item_from_url("https://x.com/FabrizioRomano/status/" + TID1)
    assert item is not None
    assert item["url"].endswith(TID1)
    assert item["body"] == TXT1


def test_item_from_url_still_uses_xscrape_in_xscrape_mode(monkeypatch):
    import config
    from sources import xscrape, twitter
    monkeypatch.setattr(config, "TWITTER_MODE", "xscrape")
    called = {"n": 0}

    def fake_fetch(url):
        called["n"] += 1
        return ("FabrizioRomano", _entry())

    monkeypatch.setattr(xscrape, "fetch_tweet", fake_fetch)
    item = twitter.item_from_url("https://x.com/FabrizioRomano/status/" + TID1)
    assert called["n"] == 1 and item["url"].endswith(TID1)


# =========================== هشدار صریح fallback قدیمی (مرحله ۱۰ درخواست)
def test_xscrape_fallback_warns_classic_is_unreliable(monkeypatch, caplog):
    """پیام fallback باید صریح بگوید classic/Nitter دیگر منبع قابل اتکا نیست."""
    import logging

    import config
    from sources import twitter
    monkeypatch.setattr(config, "TWITTER_MODE", "xscrape")
    monkeypatch.setattr(config, "XSCRAPE_FALLBACK_CLASSIC", True)
    monkeypatch.setattr(config, "XSCRAPE_MAX_CONSECUTIVE_DEAD_CYCLES", 1)
    monkeypatch.setattr(twitter, "_load", lambda: None)
    monkeypatch.setattr(twitter, "_save", lambda: None)
    monkeypatch.setattr(twitter, "_due_accounts", lambda: ["deaduser"])
    monkeypatch.setattr(twitter, "_state", {"xscrape_dead_cycles": 0})
    monkeypatch.setattr("sources.xscrape.scrape_user", lambda u, count=None: [])
    monkeypatch.setattr(twitter, "_fetch_classic", lambda limit=6: [])
    monkeypatch.setattr(twitter.health, "record_counter", lambda *a, **k: None)

    with caplog.at_level(logging.WARNING, logger="src.twitter"):
        twitter._fetch_xscrape(limit=6)
    text = caplog.text.lower()
    assert "classic/nitter" in text
    assert "unreliable" in text or "no longer" in text