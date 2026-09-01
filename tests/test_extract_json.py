"""پارس خروجی LLM در translate._extract_json — کاملاً بدون شبکه."""
import translate

# raw واقعی از لاگ پروداکشن (2026-08-31): جواب qwen حالا با کامنت HTML
# متاداتا تمام می‌شود — تغییر سمت سرویس‌دهنده، نه کد بات.
RAW_QWEN = (
    '{ "title": "برادلی بارکولا به لیورپول پیوست", '
    '"body": "برادلی بارکولا قرمز شد!\n\n#LFC", '
    '"importance": "high", "tags": ["نقل‌وانتقالات", "لیورپول"] }'
    '  <!-- qwen_metadata: {"response_id":"06a424f4-701d-4c9a-a7c6-7ac246e88444",'
    '"request_id":"428a7e6d-ca7d-4569-8cd1-3229fa171b6d"} -->'
)


def test_extract_json_ignores_trailing_html_comment():
    """کامنت متاداتای انتهای جواب نباید JSON اصلی را خراب کند."""
    data = translate._extract_json(RAW_QWEN)
    assert data is not None, "جواب سالم قومن نامعتبر درنشارفت شد"
    assert data["title"] == "برادلی بارکولا به لیورپول پیوست"
    assert "قرمز شد" in data["body"]


def test_extract_json_plain_still_works():
    data = translate._extract_json('{"title": "t", "body": "بدنه"}')
    assert data == {"title": "t", "body": "بدنه"}


def test_extract_json_codefence_still_works():
    raw = '```json\n{"title": "t", "body": "بدنه"}\n```'
    assert translate._extract_json(raw)["body"] == "بدنه"


def test_extract_json_unterminated_trailing_junk():
    """کامنت ناکمل / بریده‌شده در انتها هم مخرب نباشد."""
    raw = ('{"title": "t", "body": "بدنه"}'
           ' <!-- qwen_metadata: {"response_id":"abc')
    data = translate._extract_json(raw)
    assert data is not None and data["title"] == "t"


def test_extract_json_braces_inside_metadata_do_not_confuse():
    """حتی اگر کامنت چند تا آکولاد داشته باشد، اجسن اصلی باید برگردد."""
    raw = ('{"title": "t", "body": "بدنه"}'
           ' <!-- meta: {"a":{"b":1}} extra { not json')
    data = translate._extract_json(raw)
    assert data is not None and data["title"] == "t"


def test_extract_json_salvages_malformed_qwen_output():
    """خروجی خراب qwen با تکرار کلیدها و آکولادهای نامنظم باید حداقل title/body/importance را بگیرد."""
    raw = (
        '{"title": "تما{"شای گل‌های دیtitle": "تروز از کنار زمین 🎬",صاویر کنار زمین از "body": '
        '"تما گل‌های دیروز 🎬شای گل‌های دیروز از", "body": "تصاو کنار زمین 🎬", '
        '"importanceیر کنار زمین از گل‌های دی": "normal", "tags": ["روز 🎬", "importance":'
        'لیورپول", "گل", "normal", "tags": ["لی "آنفیلد"]}ورپول", "گل", "کنار_زمین"]}'
    )
    data = translate._extract_json(raw)
    assert data is not None
    assert "title" in data
    assert "body" in data
    assert "importance" in data
    assert isinstance(data.get("tags", []), list)


def test_rejects_gibberish_qwen_salvage():
    """ترجمه‌های نامفهوم و کلمه‌به‌کلمه‌ی خراب باید رد شوند حتی اگر از salvage بیرون بیایند."""
    body = "🔴 **خ کار نخواهد بود،بر جدید از وضعیت نقل مگر اینکه یک‌وانتق هدف بلندالات لیورپمدت در دسترس قرارول**"
    bad = {
        "title": "لیورپول",
        "body": body,
        "importance": "high",
        "tags": ["لیورپول"],
    }
    assert not translate._looks_like_valid_translation(bad["body"])
    assert not translate._looks_like_valid_translation(bad["title"])
