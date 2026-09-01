"""چند ویدیو — item باید همه‌ی ویدیوهای relay را در video_urls نگه دارد — بدون شبکه."""

import sources.twitter as twitter


def _entry_with_media(media):
    return {
        "title": "x",
        "link": "https://x.com/testuser/status/%s" % "1700000000000000000",
        "summary": "x",
        "_xscrape_media": media,
    }


def test_attach_media_sets_all_video_urls(monkeypatch):
    """آیتم با ۲ ویدیو در relay → video_urls باید هر ۲ را داشته باشد."""
    media = [
        {"type": "video", "url": "https://video.twimg.com/low1.mp4"},
        {"type": "video", "url": "https://video.twimg.com/low2.mp4"},
        {"type": "image", "url": "https://pbs.twimg.com/photo.jpg"},
    ]
    monkeypatch.setattr(twitter, "resolve_video",
                        lambda user, tid, scraped_mp4=None: {
                            "video_url": scraped_mp4, "thumbnail_url": None,
                            "media_urls": [], "source": "xscrape"})
    item = {"url": "https://x.com/testuser/status/1700000000000000000"}
    twitter._attach_media(item, _entry_with_media(media), "testuser")
    assert item["video_url"] == "https://video.twimg.com/low1.mp4"
    assert item["video_urls"] == [
        "https://video.twimg.com/low1.mp4",
        "https://video.twimg.com/low2.mp4",
    ]
    assert item["images"]  # عکس هم حفظ شده


def test_send_media_group_supports_video_album_with_caption():
    """آلبوم چند ویدیویی باید در sendMediaGroup با نوع video و کپشن روی مورد اول ارسال شود."""
    import telegram_api

    tg = telegram_api.Telegram(token="test-token")
    seen = {}

    def fake_call(method, **params):
        seen["method"] = method
        seen["params"] = params
        return {"ok": True, "result": [{"message_id": 1}]}

    tg.call = fake_call

    res = tg.send_media_group(
        chat_id=-100,
        image_urls=["https://a.mp4", "https://b.mp4"],
        caption="caption",
        silent=True,
        media_type="video",
    )

    assert res is not None
    assert seen["method"] == "sendMediaGroup"
    assert seen["params"]["media"][0]["type"] == "video"
    assert seen["params"]["media"][0]["caption"] == "caption"
    assert seen["params"]["media"][0]["parse_mode"] == "HTML"
