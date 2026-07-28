"""خبر نمونه برای تست کردن مسیر ترجمه + تلگرام، حتی وقتی هیچ خبر تازه‌ای نیست."""
import os
import time

SAMPLES = [
    {
        "source": "Fabrizio Romano",
        "source_tag": "Fabrizio Romano",
        "url": "https://x.com/FabrizioRomano/status/000000000000000001",
        "title": "Liverpool are working on Bradley Barcola deal",
        "body": (
            "To be clear: Liverpool are working on Bradley Barcola deal but don't expect "
            "anything to be agreed in the next hours. Talks are ongoing and will take time.\n\n"
            "I can confirm and explain today that Barcola is completely open and keen on the "
            "move to Liverpool. He's attracted by the Liverpool project and believes the Reds "
            "are the best option for his career.\n\n"
            "Barcola has no control over negotiations between the two clubs and it's normal "
            "that Paris Saint-Germain want a big fee to sell him. Still, I don't think the "
            "transfer will happen for \u20ac170m; in my view it will be done for less.\n\n"
            "Liverpool are in contact with the other side, so let's wait and see what happens next."
        ),
        # عکس تست روی دیسک است تا مسیر ارسال عکس بدون وابستگی به سایت بیرونی تست شود
        "image": os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sample.png"),
        "priority": True,
    },
    {
        "source": "LFC Official",
        "source_tag": "Liverpool FC",
        "url": "https://www.liverpoolfc.com/news/sample-official-000000000000000002",
        "title": "Arne Slot provides injury update ahead of Premier League opener",
        "body": (
            "Arne Slot has confirmed that the squad came through pre-season without any major "
            "concerns ahead of the Premier League opener.\n\n"
            "Speaking at the AXA Training Centre in Kirkby, the head coach said the group has "
            "trained well and that a decision on the starting line-up will be made after the "
            "final session.\n\n"
            "'The players have worked extremely hard,' Slot said. 'We are in a good place and "
            "we know how difficult the first game of the season always is.'"
        ),
        "image": None,
    },
]


def get(index=0, unique=True):
    """یک خبر نمونه برمی‌گرداند. unique=True یعنی لینک یکتا می‌شود تا
    فیلتر تکراری بودن جلوی تست مجدد را نگیرد."""
    item = dict(SAMPLES[index % len(SAMPLES)])
    if unique:
        item["url"] = f"{item['url']}?t={int(time.time())}"
    return item


def all_samples(unique=True):
    return [get(i, unique) for i in range(len(SAMPLES))]
