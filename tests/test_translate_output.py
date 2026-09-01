"""پاسخ نهایی ترجمه — حذف هشتگ — کاملاً بدون شبکه."""

import translate

BS = chr(92)   # backslash
NL = chr(10)


# جواب واقعی qwen: JSON + هشتگ‌های آخر + کامنت متادیتا (با \x3C) در یک رشته
RAW_QWEN_HASHTAGS = (
    '{ "title": "نظرات درباره مصدومیت مسکورا", '
    '"body": "کریستین مسکورا مجبور شد با مصدومیت همسترینگ از زمین خارج شود. '
    'زمان بازگشت اگر سفتی باشد کمتر از یک هفته است. اسکن لازم است. \\n#AFC #Arsenal #ArsenalFC #FPL #FPLCommunity", '
    '"importance": "normal", "tags": [] }'
    + "  <!-- qwen_metadata: {\"response_id\":\"abc\",\"request_id\":\"def\"} -->"
)


class _Msg:
    content = RAW_QWEN_HASHTAGS


class _Choice:
    message = _Msg()


class _Resp:
    choices = [_Choice()]
    model = "openai/qwen3.7-plus#2"


class _FakeRouter:
    def completion(self, **kwargs):
        return _Resp()


def test_strip_hashtags_removes_all_hashtags():
    body = "کریستین مسکورا مصدوم شد." + NL + "#AFC #Arsenal #FPL"
    out = translate._strip_hashtags(body)
    assert "#" not in out
    assert "کریستین مسکورا" in out
    assert "Arsenal" not in out


def test_strip_hashtags_persian_hashtag():
    assert "#" not in translate._strip_hashtags("خبر فوری درباره لیورپول #لیورپول")


def test_strip_hashtags_cleans_x3c_artifact():
    out = translate._strip_hashtags("اگر سفتی: " + BS + "x3C1 هفته")
    assert BS + "x3C" not in out and BS + "x3c" not in out
    assert "هفته" in out


def test_strip_hashtags_keeps_normal_text_untouched():
    s = "متن ساده بدون هشتگ"
    assert translate._strip_hashtags(s) == s


def test_is_relevant_counts_club_hashtags():
    """#LFC / #Liverpool باید توییت را مرتبط کند (regression lock)."""
    import sources.twitter as twitter
    assert twitter._is_relevant("Breaking: deal agreed here #LFC", "FabrizioRomano")
    assert twitter._is_relevant("full analysis out now #Liverpool", "FabrizioRomano")
    assert not twitter._is_relevant("Arsenal beat Spurs tonight #AFC #COYS",
                                    "FabrizioRomano")


def test_translate_llm_output_has_no_hashtags(monkeypatch):
    """مسیر کامل: خروجی مدل با هشتگ → خروجی نهایی بدون هشتگ و بدون artifact."""
    monkeypatch.setattr(translate, "_get_router",
                        lambda: (_FakeRouter(), ["qwen3.7-plus#2"]))
    monkeypatch.setattr(translate, "_deployments", lambda: ([], [], False))
    monkeypatch.setattr(translate.health, "record_ok", lambda *a, **k: None)
    monkeypatch.setattr(translate.health, "record_counter", lambda *a, **k: None)
    monkeypatch.setattr(translate.health, "record_fail", lambda *a, **k: None)
    item = {"title": "Mosquera injury update",
            "body": "Mosquera left the pitch with a hamstring injury."}
    data = translate.translate(item)
    assert data is not None
    assert "#" not in (data["body"] or ""), data["body"]
    assert "#" not in (data["title"] or "")
    assert BS + "x3C" not in (data["body"] or "")
    assert "مسکورا" in data["body"]