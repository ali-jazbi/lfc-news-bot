"""مقایسه کیفیت ترجمه — python benchmark.py

دو متن سخت را به تک‌تک سرویس‌های زنجیره می‌دهد و خروجی‌ها را کنار هم می‌گذارد.
نتیجه هم در ترمینال چاپ می‌شود هم در فایل benchmark.md ذخیره می‌شود
(خواندن فارسی در ترمینال ویندوز بهم‌ریخته است، فایل md را باز کن).

دستورها:
    python benchmark.py            هر دو متن، همه سرویس‌ها
    python benchmark.py 1          فقط متن شماره ۱
"""
import re
import sys
import time

import config
import translate

OK = "\u2705"
NO = "\u274C"
WARN = "\u26A0\uFE0F"

# ============================================================
#  متن‌های آزمون — عمداً پر از تله
# ============================================================
# تله‌ها: اصطلاح فوتبالی، اعداد و مبالغ، نقل‌قول در نقل‌قول،
# اسم بازیکن که شبیه کلمه معمولی است، اصطلاح عامیانه، تاریخ بریتانیایی

TESTS = [
    {
        "id": 1,
        "label": "توییت سبک رومانو — پر از اصطلاح نقل‌وانتقالی",
        "item": {
            "source": "romano",
            "source_tag": "Fabrizio Romano",
            "url": "https://x.com/FabrizioRomano/status/1",
            "priority": True,
            "title": "Liverpool close on deal",
            "body": (
                "\U0001F534 EXCLUSIVE: Liverpool have entered advanced talks to sign the "
                "22-year-old Brazilian winger, with the Reds prepared to trigger his "
                "\u00a352m release clause before deadline day.\n\n"
                "Personal terms are no issue \u2014 the player has already agreed a "
                "five-year deal worth around \u00a3140,000-a-week, plus \u00a38m in add-ons "
                "tied to appearances and Champions League qualification. There is also "
                "a 15% sell-on clause inserted at the request of his current club.\n\n"
                "Arne Slot has been pushing for a wide forward since pre-season, having "
                "been left short after Mohamed Salah's hamstring injury ruled him out "
                "for six weeks. The Dutchman told reporters on Friday: \"We don't need "
                "to panic in the market, but if the right profile is there, the club "
                "know my thinking.\"\n\n"
                "Medical is being scheduled for Monday at the AXA Training Centre. "
                "The deal is not done yet \u2014 but it's close. Here we go soon? "
                "Not yet, but Liverpool are in the driving seat.\n\n"
                "More to follow. \U0001F534 #LFC #YNWA https://t.co/abc123"
            ),
        },
    },
    {
        "id": 2,
        "label": "خبر رسمی سایت باشگاه — طولانی، رسمی، توصیفی",
        "item": {
            "source": "lfc",
            "source_tag": "Liverpool FC",
            "url": "https://www.liverpoolfc.com/news/x",
            "priority": False,
            "title": "Slot reflects on gritty win as Reds keep clean sheet at Anfield",
            "body": (
                "Arne Slot praised his side's resilience after Liverpool ground out a "
                "1-0 victory over Everton in the Merseyside derby at Anfield on Saturday "
                "afternoon, a result that lifts the Reds to within two points of the "
                "summit with eleven matches remaining.\n\n"
                "It was far from vintage. Liverpool struggled to break down a stubborn "
                "low block for the best part of an hour, and it took an injury-time "
                "winner from academy graduate Conor Bradley \u2014 his first senior goal "
                "at the Kop end \u2014 to separate the sides. Alisson was rarely troubled "
                "but produced a smart stop at his near post to preserve a fourth clean "
                "sheet in five league outings.\n\n"
                "\"Sometimes you have to win ugly,\" Slot said afterwards. \"In this "
                "league, if you only win the pretty games, you finish fourth. The lads "
                "dug in, they stayed patient, and Conor got his reward. He's been "
                "knocking on the door since pre-season.\"\n\n"
                "Virgil van Dijk, who captained the side for the 150th time, was booked "
                "in the second half and will miss the trip to Brighton through "
                "suspension. Ryan Gravenberch was withdrawn on 71 minutes as a "
                "precaution with tightness in his calf, though Slot played down concerns, "
                "insisting the midfielder should be available for Wednesday's Champions "
                "League tie.\n\n"
                "Attention now turns to the AXA Training Centre in Kirkby, where the "
                "squad will reconvene on Monday. Kick-off at the Amex is 3pm GMT on "
                "21 February."
            ),
        },
    },
]

# چیزهایی که حتماً باید در خروجی باشند (عدد یا معادل فارسی)
MUST_HAVE = {
    1: [
        (["52", "\u06f5\u06f2"], "مبلغ شرط فسخ ۵۲ میلیون"),
        (["22", "\u06f2\u06f2"], "سن ۲۲ سال"),
        (["\u0644یورپول"], "نام لیورپول"),
        (["\u0627سلوت"], "نام آرنه اسلوت"),
        (["\u0635لاح"], "نام صلاح"),
    ],
    2: [
        (["1-0", "\u06f1-\u06f0", "\u06f0-\u06f1", "یک بر صفر"], "نتیجه ۱-۰"),
        (["\u0628ردلی", "\u0628رادلی"], "نام کانر بردلی"),
        (["\u0622نفیلد"], "نام آنفیلد"),
        (["\u062fربی"], "دربی مرسی‌ساید"),
        (["\u0641ن‌دایک", "\u0641ن دایک"], "نام فن‌دایک"),
    ],
}

# ترجمه‌های تحت‌اللفظی که سوتی محسوب می‌شوند
RED_FLAGS = [
    ("صندلی راننده", "driving seat تحت‌اللفظی ترجمه شده"),
    ("در حال رانندگی", "driving seat تحت‌اللفظی"),
    ("برگه تمیز", "clean sheet تحت‌اللفظی"),
    ("ورق تمیز", "clean sheet تحت‌اللفظی"),
    ("ملافه تمیز", "clean sheet تحت‌اللفظی"),
    ("بلوک پایین", "low block تحت‌اللفظی"),
    ("پزشکی در حال برنامه‌ریزی", "ترجمه ماشینی medical"),
    ("در حال کوبیدن به در", "knocking on the door تحت‌اللفظی"),
    ("بردن زشت", "win ugly تحت‌اللفظی"),
    ("هینگ وی گو", "here we go ترجمه نشده"),
    ("پسران حفر کردند", "lads dug in تحت‌اللفظی"),
]

LATIN = re.compile(r"[A-Za-z]{3,}")


def score(test_id, tr):
    """چک‌های خودکار روی خروجی. خروجی: (امتیاز, سقف, یادداشت‌ها)"""
    text = (tr.get("title", "") + "\n" + tr.get("body", ""))
    notes = []
    got = 0
    total = 0

    # ۱) اطلاعات کلیدی حفظ شده؟
    for variants, label in MUST_HAVE[test_id]:
        total += 1
        if any(v in text for v in variants):
            got += 1
        else:
            notes.append(f"{NO} جا افتاد: {label}")

    # ۲) واژه‌نامه رعایت شده؟
    total += 1
    if "\u0627سلات" in text or "\u0627سلاتی" in text:
        notes.append(f"{NO} Slot به جای «اسلوت» غلط آوانگاری شده")
    else:
        got += 1

    # ۳) انگلیسی جامانده
    total += 1
    leftovers = sorted(set(LATIN.findall(text)))
    if leftovers:
        notes.append(f"{WARN} انگلیسی جامانده: {', '.join(leftovers[:6])}")
    else:
        got += 1

    # ۴) ترجمه تحت‌اللفظی
    total += 1
    flags = [why for phrase, why in RED_FLAGS if phrase in text]
    if flags:
        for f in flags:
            notes.append(f"{NO} سوتی: {f}")
    else:
        got += 1

    # ۵) طول مناسب کپشن تلگرام
    total += 1
    n = len(tr.get("body", ""))
    if n > 1000:
        notes.append(f"{NO} متن خیلی بلند است ({n} کاراکتر، سقف کپشن عکس ۱۰۲۴)")
    elif n < 150:
        notes.append(f"{WARN} متن خیلی کوتاه است ({n} کاراکتر) — محتوا حذف شده؟")
    else:
        got += 1

    # ۶) تشخیص اهمیت
    total += 1
    want = "high" if test_id == 1 else "normal"
    if tr.get("importance") != want:
        notes.append(f"{WARN} importance={tr.get('importance')} ولی انتظار {want} بود")
    else:
        got += 1

    return got, total, notes


def run_one(test, out):
    tid = test["id"]
    item = test["item"]

    banner = f"\n{'=' * 62}\nمتن شماره {tid}: {test['label']}\n{'=' * 62}"
    print(banner)
    out.append(f"\n\n# متن شماره {tid} — {test['label']}\n")
    out.append(f"**طول متن انگلیسی:** {len(item['body'])} کاراکتر\n")
    out.append("<details><summary>متن اصلی</summary>\n\n```\n"
               + item["body"] + "\n```\n</details>\n")

    prompt = translate._build_prompt(item)
    results = []

    for name, kind, fn in translate._chain():
        print(f"\n▶ {name} ...")
        t0 = time.time()
        try:
            data = fn(item) if kind == "plain" else translate._extract_json(fn(prompt))
            dt = time.time() - t0
        except Exception as e:
            print(f"  {NO} {e}")
            out.append(f"\n## {name}\n\n{NO} خطا: `{e}`\n")
            continue

        if not data or not data.get("body"):
            print(f"  {NO} خروجی نامعتبر")
            out.append(f"\n## {name}\n\n{NO} خروجی نامعتبر\n")
            continue

        # دقیقاً همان پردازشی که در خط تولید روی خروجی انجام می‌شود
        # تا عددهای این گزارش با واقعیت ربات یکی باشد
        data.setdefault("title", "")
        data.setdefault("importance", "normal")
        data["body"] = translate._trim(str(data["body"]))
        data["title"] = str(data["title"]).strip()[:120]
        translate._fix_importance(item, data)
        got, total, notes = score(tid, data)
        results.append((name, got, total, dt))

        print(f"  {OK} امتیاز {got}/{total}  —  {dt:.1f}s")
        for n in notes:
            print("    " + n)

        out.append(f"\n## {name}\n")
        out.append(f"**امتیاز:** {got}/{total} &nbsp;|&nbsp; "
                   f"**زمان:** {dt:.1f}s &nbsp;|&nbsp; "
                   f"**طول:** {len(data['body'])} کاراکتر &nbsp;|&nbsp; "
                   f"**اهمیت:** {data['importance']}\n")
        out.append(f"\n**عنوان:** {data['title']}\n")
        out.append(f"\n{data['body']}\n")
        if data.get("tags"):
            out.append(f"\n`تگ‌ها: {' ، '.join(map(str, data['tags']))}`\n")
        if notes:
            out.append("\n**ایرادها:**\n")
            for n in notes:
                out.append(f"- {n}\n")
        else:
            out.append(f"\n{OK} هیچ ایراد خودکاری پیدا نشد.\n")

    return results


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    tests = [t for t in TESTS if not only or str(t["id"]) == only]

    if not translate._chain():
        print(f"{NO} هیچ سرویس ترجمه‌ای فعال نیست. اول python doctor.py را بزن.")
        sys.exit(1)

    out = ["# مقایسه کیفیت ترجمه\n",
           f"زنجیره: {' \u2190 '.join(translate.chain_names())}\n"]
    totals = {}

    for t in tests:
        for name, got, total, dt in run_one(t, out):
            g, tot, secs, cnt = totals.get(name, (0, 0, 0.0, 0))
            totals[name] = (g + got, tot + total, secs + dt, cnt + 1)

    # جدول نهایی
    print(f"\n{'=' * 62}\nجمع‌بندی\n{'=' * 62}")
    out.append("\n\n---\n\n# جمع‌بندی\n\n")
    out.append("| سرویس | امتیاز | درصد | میانگین زمان |\n|---|---|---|---|\n")

    ranked = sorted(totals.items(), key=lambda kv: (-kv[1][0] / max(kv[1][1], 1), kv[1][2]))
    for i, (name, (g, tot, secs, cnt)) in enumerate(ranked, 1):
        pct = 100 * g / max(tot, 1)
        avg = secs / max(cnt, 1)
        medal = "\U0001F947" if i == 1 else ("\U0001F948" if i == 2 else "  ")
        print(f"{medal} {name:24} {g}/{tot}  ({pct:.0f}%)  میانگین {avg:.1f}s")
        out.append(f"| {medal} {name} | {g}/{tot} | {pct:.0f}% | {avg:.1f}s |\n")

    if ranked:
        best = ranked[0][0]
        tip = (f"\nبهترین: **{best}** — این را اول TRANSLATE_ORDER بگذار.\n")
        print(tip)
        out.append(tip)

    out.append("\n> چک‌ها خودکارند و فقط خطاهای آشکار را می‌گیرند. "
               "روانی و لحن را خودت قضاوت کن.\n")

    with open("benchmark.md", "w", encoding="utf-8") as f:
        f.write("".join(out))
    print("خروجی کامل در فایل benchmark.md ذخیره شد — آن را باز کن و متن‌ها را بخوان.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
