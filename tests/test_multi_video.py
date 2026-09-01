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
