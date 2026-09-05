"""تست نام‌های فارسی فرمان ویرایش."""


def test_persian_edit_command_is_handled(patched_main, sample_item, monkeypatch):
    import main
    called = []
    monkeypatch.setattr(main, "_apply_reply_edit", lambda m: called.append(m))
    m = {"text": "ادیت\nتیتر\nبدنه", "from": {"id": 1}, "chat": {"id": -100}}
    main.handle_message(m)
    assert called == [m]


def test_persian_edit_command_with_bot_mention_is_handled(patched_main, monkeypatch):
    import main
    called = []
    monkeypatch.setattr(main, "_apply_reply_edit", lambda m: called.append(m))
    m = {"text": "ادیت@my_bot\nتیتر\nبدنه", "from": {"id": 1}, "chat": {"id": -100}}
    main.handle_message(m)
    assert called == [m]


def test_ordinary_text_does_not_trigger_edit(patched_main, monkeypatch):
    import main
    called = []
    monkeypatch.setattr(main, "_apply_reply_edit", lambda m: called.append(m))
    m = {"text": "ادیتور فوتبال", "from": {"id": 1}, "chat": {"id": -100}}
    main.handle_message(m)
    assert not called
