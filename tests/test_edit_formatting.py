"""رگرسیون ویرایش /edit — فرمت ادمین (بولد/کووت) باید دقیقاً سر جایش بماند.

باگ قدیمی: آفست‌های entity روی «متن خام» حساب می‌شد ولی متن بعد از strip و
حذف «#» برداشته می‌شد → خط خالی یا «#» فرمت را جابه‌جا می‌کرد (تایتل نیمه‌بولد،
کووت نیمه‌اعمال). این تست‌ها هر دو حالت و حالت‌های مرزی را پوشش می‌دهند.
"""
import formatter


def _mk(patched_main, sample_item, admin_msg):
    """ذخیره خبر + اتصال به message_id پیش‌نمایش."""
    import db
    item = dict(sample_item)
    item["translated"] = {"title": "t", "body": "b", "importance": "normal"}
    key = db.save(item, status="sent_admin")
    db.set_admin_msg(key, admin_msg)
    return key


def _msg(text, ents, msg_id):
    return {
        "chat": {"id": -100},
        "reply_to_message": {"message_id": msg_id},
        "text": text,
        "entities": ents,
        "from": {"id": 1},
    }


def test_bold_title_and_expandable_quote_exact(patched_main, sample_item):
    """/edit استاندارد: تیتر بولد، بخشی از بدنه کووت تاشو."""
    import db
    import main
    _mk(patched_main, sample_item, 555)
    text = "/edit\nتیتر آزمایشی\nبدنه خبر اینجاست"
    ents = [
        {"offset": 6, "length": 12, "type": "bold"},
        {"offset": 24, "length": 3, "type": "expandable_blockquote"},
    ]
    assert main._apply_reply_edit(_msg(text, ents, 555)) is True
    tr = db.get_by_admin_msg(555)["payload"]["translated"]
    assert tr["edited_title_html"] == "<b>تیتر آزمایشی</b>"
    assert tr["edited_body_html"] == "بدنه <blockquote expandable>خبر</blockquote> اینجاست"


def test_blank_line_and_hash_do_not_shift_format(patched_main, sample_item):
    """خط خالی بعد از /edit و «#» اول عنوان — فرمت نباید جابه‌جا شود (باگ اصلی)."""
    import db
    import main
    _mk(patched_main, sample_item, 556)
    text = "/edit\n\n# تیتر دوم\nبدنه سوم"
    ents = [{"offset": 9, "length": 8, "type": "bold"}]
    assert main._apply_reply_edit(_msg(text, ents, 556)) is True
    tr = db.get_by_admin_msg(556)["payload"]["translated"]
    assert tr["edited_title_html"] == "<b>تیتر دوم</b>"
    assert tr["edited_body_html"] == "بدنه سوم"


def test_emoji_offsets_are_utf16(patched_main, sample_item):
    """ایموجی در تیتر = ۲ واحد UTF-16 — بولد باید بعد از ایموجی دقیق بنشیند."""
    import db
    import main
    _mk(patched_main, sample_item, 557)
    text = "/edit\n🔴 تیتر\nبدنه"
    ents = [{"offset": 9, "length": 4, "type": "bold"}]
    assert main._apply_reply_edit(_msg(text, ents, 557)) is True
    tr = db.get_by_admin_msg(557)["payload"]["translated"]
    assert tr["edited_title_html"] == "🔴 <b>تیتر</b>"


def test_markdown_fallback_without_entities(patched_main, sample_item):
    """بدون entity تلگرام → مارک‌داون **بولد** هنوز کار می‌کند."""
    import db
    import main
    _mk(patched_main, sample_item, 558)
    text = "/edit\nتیتر **مهم**\nبدنه"
    assert main._apply_reply_edit(_msg(text, [], 558)) is True
    tr = db.get_by_admin_msg(558)["payload"]["translated"]
    assert tr["edited_title_html"] == "تیتر <b>مهم</b>"


def test_unknown_entity_type_never_eats_text(patched_main, sample_item):
    """entity ناشناخته (mention و...) متن را حذف نمی‌کند — فقط بدون فرمت می‌ماند."""
    import db
    import main
    _mk(patched_main, sample_item, 560)
    text = "/edit\nتیتر با منشن\nبدنه"
    ents = [{"offset": 6, "length": 12, "type": "mention"}]
    assert main._apply_reply_edit(_msg(text, ents, 560)) is True
    tr = db.get_by_admin_msg(560)["payload"]["translated"]
    assert tr["edited_title_html"] == "تیتر با منشن"


def test_caption_renders_admin_formatting_verbatim(patched_main, sample_item):
    """پست نهایی: تیتر بولدِ ادمین + کووت تاشو عیناً حفظ شود."""
    import db
    import main
    _mk(patched_main, sample_item, 559)
    text = "/edit\nتیتر آزمایشی\nبدنه خبر اینجاست"
    ents = [
        {"offset": 6, "length": 12, "type": "bold"},
        {"offset": 24, "length": 3, "type": "expandable_blockquote"},
    ]
    assert main._apply_reply_edit(_msg(text, ents, 559)) is True
    row = db.get_by_admin_msg(559)
    cap = formatter.build_caption(row["payload"], row["payload"]["translated"])
    assert "<b>تیتر آزمایشی</b>" in cap
    assert "<blockquote expandable>خبر</blockquote>" in cap
