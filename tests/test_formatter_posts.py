"""قواعد جدید قالب پست — تایتل شرطی، ایموجی آمار، مصاحبه، کووت تلگرامی."""
import formatter


def _item(**kw):
    base = {"source_tag": "Opta Analyst", "url": "https://x.com/x/status/1"}
    base.update(kw)
    return base


def test_stats_lines_use_blue_marker_only():
    tr = {"title": "آمار بازیکن لیورپول در شب برد", "importance": "normal",
          "body": "آمار درخشان بازیکن در بازی دیشب:\n"
                  "👟 ۳۲ از ۳۸ پاس صحیح\n⚔️ ۹ از ۱۰ نبرد موفق\n"
                  "🫡 ۷ دفع توپ\n🏃 ۲ از ۳ دریبل موفق\n"
                  "او نمایش فوق‌العاده‌ای داشت و جایزه مرد میدان را گرفت و امشب ستاره زمین بود."}
    cap = formatter.build_caption(_item(), tr)
    assert "👟" not in cap and "🫡" not in cap and "🏃" not in cap
    assert "🔹 ۳۲ از ۳۸ پاس صحیح" in cap
    assert "🔹 ۲ از ۳ دریبل موفق" in cap


def test_short_tweet_keeps_distinct_title_without_duplication():
    tr = {"title": "سه امتیاز قرمزها در پورتمن رود",
          "body": "سه امتیاز در پورتمن رود 💪", "importance": "high"}
    cap = formatter.build_caption(_item(), tr)
    assert "🔴 <b>سه امتیاز قرمزها در پورتمن رود</b>" in cap
    assert cap.count("پورتمن رود") == 2


def test_short_tweet_does_not_duplicate_identical_title():
    tr = {"title": "سه امتیاز قرمزها در پورتمن رود",
          "body": "سه امتیاز قرمزها در پورتمن رود 💪", "importance": "high"}
    cap = formatter.build_caption(_item(), tr)
    assert cap.count("سه امتیاز") == 1
    assert "<b>" not in cap


def test_long_post_keeps_bold_title():
    tr = {"title": "تحلیل تاکتیکی برد لیورپول", "importance": "normal",
          "body": "لیورپول با نمایشی حساب‌شده توانست خط دفاعی حریف را از هم بپاشد. " * 6}
    cap = formatter.build_caption(_item(), tr)
    assert cap.splitlines()[0].startswith("⚪️ <b>")


def test_interview_post_gets_microphone_icon():
    tr = {"title": "مصاحبه انحصاری با کپیتان تیم", "importance": "normal",
          "body": "در گفت‌وگوی اختصاصی، فان دایک درباره فصل جدید توضیح داد که تیم "
                  "آماده‌ی رقابت‌های پیش روست و هواداران باید امیدوار باشند چون کیفیت "
                  "سکواد بالاست و هدف قهرمانی است در این فصل طولانی و پرفشار پیش رو."}
    cap = formatter.build_caption(_item(), tr)
    assert cap.startswith("🎙 ")


def test_single_quote_becomes_telegram_blockquote():
    tr = {"title": "واکنش کودی گاکپو پس از پیروزی", "importance": "normal",
          "body": "«امروز بازی خوبی بود، اما باید در برخی موارد بهتر شویم. "
                  "این برد بسیار لازم بود و خوشحالم که سه امتیاز را گرفتیم.»"}
    cap = formatter.build_caption(_item(), tr)
    assert "<blockquote expandable>«" in cap
    assert "واکنش کودی گاکپو" in cap


def test_quote_with_speaker_keeps_speaker_outside():
    tr = {"title": "واکنش اسلوت", "importance": "normal",
          "body": "آرنه اسلوت: «ما مستحق برد بودیم و بازیکنان عالی جنگیدند تا آخرین ثانیه.»"}
    cap = formatter.build_caption(_item(), tr)
    assert "<blockquote expandable>«ما مستحق برد بودیم" in cap
    assert "آرنه اسلوت" in cap.splitlines()[0]


def test_quote_text_is_not_repeated_in_title():
    quote = "«مک‌آلیستر بازیکن بسیار باهوشی است. از نظر جایگیری فوق‌العاده هوشمند است...»"
    tr = {"title": f"آندونی ایرائولا: {quote}", "importance": "normal",
          "body": quote}
    cap = formatter.build_caption(_item(), tr)
    assert cap.count("مک‌آلیستر بازیکن بسیار باهوشی است") == 1
    assert quote not in cap.splitlines()[0]


def test_keyboard_has_original_text_button():
    kb = formatter.keyboard("abc123")
    flat = [b for row in kb["inline_keyboard"] for b in row]
    orig = [b for b in flat if b["callback_data"] == "orig:abc123"]
    assert orig and "متن اصلی" in orig[0]["text"]
