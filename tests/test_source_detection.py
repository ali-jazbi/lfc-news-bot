"""منبع‌یابی چندگانه از همه‌ی منشن‌ها — کاملاً بدون شبکه."""

import sources.twitter as twitter


def test_mention_at_end_after_emoji():
    """@منشن در انتها، حتی بعد از ایموجی/نویسه (کیس anfieldsociaI / Santi_J_FM)."""
    entry = {"summary": "گزارش مختصر 🔴 (@Santi_J_FM)"}
    got = twitter.detect_original_source(entry, "گزارش مختصر 🔴 (@Santi_J_FM)", "anfieldsociaI")
    assert got is not None
    assert got[0] == "Santi_J_FM"
    assert got[1]  # display name


def test_mention_middle_of_text():
    """منشن وسط متن — «به نقل از _pauljoyce»."""
    entry = {"summary": "به نقل از _pauljoyce: خبر مهم درباره لیورپول"}
    got = twitter.detect_original_source(entry, "به نقل از _pauljoyce: خبر مهم درباره لیورپول", "AnfieldSector")
    assert got is not None
    assert got[0] == "_pauljoyce"


def test_santi_handle_maps_to_name():
    """اسم انسانی Santi Aouna باید برای handle Santi_J_FM ثبت شود."""
    assert twitter.config.display_name("Santi_J_FM") == "Santi Aouna"


def test_two_mentions_both_returned():
    """دو منشن در یک توییت → اولی primary، دومی هم در لیست (منابع چندگانه)."""
    entry = {"summary": "شکستن خبر توسط _pauljoyce و تایید @FabrizioRomano 🐓"}
    primary, others, all_m = twitter.detect_original_sources(entry, "شکستن خبر توسط _pauljoyce و تایید @FabrizioRomano 🐓", "AnfieldSector")
    assert primary == "_pauljoyce"
    assert others == ["FabrizioRomano"]
    assert all_m == ["_pauljoyce", "FabrizioRomano"]


def test_no_mention_returns_none():
    entry = {"summary": "گزارش خودم از بازی"}
    got = twitter.detect_original_source(entry, "گزارش خودم از بازی", "AnfieldSector")
    assert got is None or got == (None, None)


def test_unknown_mention_still_source():
    """@منشن ناشناخته (Santi_J_FM) → همان handle به‌عنوان منبع (بدون نیاز به whitelist)."""
    entry = {"summary": "خبر اختصاصی (@Santi_J_FM)"}
    got = twitter.detect_original_sources(entry, "خبر اختصاصی (@Santi_J_FM)", "anfieldsociaI")
    assert got[0] == "Santi_J_FM"


def test_own_mention_ignored():
    """منشن خودِ اکانت → نباید منبع حساب شود."""
    entry = {"summary": "خلاصه بازی (به نقل از AnfieldSector)"}
    got = twitter.detect_original_sources(entry, "خلاصه بازی (به نقل از AnfieldSector)", "AnfieldSector")
    assert got[0] is None  # فقط خودِ اکانت منشن شده → بدون منبع


def test_build_caption_combines_multiple_sources():
    """برای چند منبع، برچسب کانال باید با & ترکیب شود؛ در HTML این به &amp; تبدیل می‌شود."""
    import formatter

    item = {
        "source_tag": "Ben Jacobs",
        "original_source": "@JacobsBen",
        "original_source_tag": "Ben Jacobs",
        "original_sources": ["@JacobsBen", "@talkSPORT"],
    }
    tr = {"body": "Hello", "title": "Title", "importance": "high"}
    caption = formatter.build_caption(item, tr)
    assert "[Ben Jacobs &amp; talkSPORT]" in caption