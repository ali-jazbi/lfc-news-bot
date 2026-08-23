<!-- samemind:install:start -->
<!-- samemind: identity + memory protocol for Claude Code. Installed by `samemind install --agent claude-code` — safe to regenerate; edit outside these markers. Docs: docs/identity-layer.md · docs/memory-protocol.md · docs/work-discipline.md -->

no Identity/User concept in this bundle — brief is identity-layer only; add one (see docs/identity-layer.md)

## samemind memory

Local git-native markdown memory (samemind / OKF bundle) — no cloud service, no API keys.
On session start, run `memory_handoff` (MCP) or `samemind handoff` for work state before re-explaining.

When a question needs past context (owner, people, projects, decisions):

1. **Search first (cheap):** `samemind recall "<q>" -k 5` or MCP `memory_search`.
2. **Read top 3–5 fully:** `samemind query get <id>` or MCP `memory_get`. At most one relation hop if still within budget.
3. **Answer with path citations** like `/entities/x.md`, `/projects/y.md`.
4. **Always end with** `## What the memory doesn't cover` — gaps for this question + staleness from each node's `timestamp`.
5. **New facts/decisions** → MCP `memory_write_inbox` only. Never write into `concepts/` / `entities/` / `projects/` as the agent.

Full protocol: docs/memory-protocol.md. Bundle root = `OKF_ROOT` env or the current directory.

## Write discipline (MUST)

The bundle holds **work**, not only facts (full spec: docs/work-discipline.md).

- Agreed a plan/position with the owner → write a `Plan`/`Decision` to `inbox/` **now** (MCP `memory_write_inbox`). "Later" = didn't happen.
- Plan changed → write a **new** `Plan` with `relations.supersedes: /projects/<old>.md`; mark old `status: superseded`. Plans/Decisions are append-only.
- Session ended → write a `Session` to `inbox/` (`engine`, `date`, `## Done` / `## Decided` / `## Next`).
- Task changed status → edit the `Task` **in place**. `status: blocked` requires a non-empty `blocked_reason`.

`samemind query validate` warns on Plan/Task missing `status`, bad `status`, or a blocked Task without a reason.

Tools on this bundle: `samemind query|recall|gde|brief|handoff|forget|serve` (or MCP `memory_search/get/list/write_inbox/handoff`).
This block was installed for **Claude Code** by `samemind install` — safe to re-run, safe to delete by hand.
<!-- samemind:install:end -->

<!-- samemind:project:start -->
### benchmark
# مقایسه کیفیت ترجمه
زنجیره: qwen3.7-plus ← opencode-deepseek ← opencode-ling ← ling-openrouter ← gemini-flash ← gemini-flash-lite ← groq-qwen ← nemotron-super ← groq ← openrouter ← مترجم گوگل


# متن شماره 1 — توییت سبک رومانو — پر از اصطلاح نقل‌وانتقالی
**طول متن انگلیسی:** 957 کاراکتر
<details><summary>متن اصلی</summary>

```
🔴 EXCLUSIVE: Liverpool have entered advanced talks to sign the 22-year-old Brazilian winger, with the Reds prepared to trigger his £52m release clause before deadline day.

Personal terms are no issue — the player has already agreed a five-year deal worth around £140,000-a-week, plus £8m in add-ons tied to appearances and Champions League qualification. There is also a 15% sell-on clause inserted at the request of his current club.

Arne Slot has been pushing for a wide forward since pre-season, having been left short after Mohamed Salah's hamstring injury ruled him out for six weeks. The Dutchman told reporters on Friday: "We don't need to panic in the market, but if the right profile is there, the club know my thinking."

Medical is being scheduled for Monday at the AXA Training Centre. The deal is not done yet — but it's close. Here we go soon? Not yet, but Liverpool are in the driving seat.

More to follow. 🔴 #LFC #YNWA https://t.co/abc123
```
</details>

## qwen3.7-plus
**امتیاز:** 10/10 &nbsp;|&nbsp; **زمان:** 11.0s &nbsp;|&nbsp; **طول:** 792 کاراکتر &nbsp;|&nbsp; **اهمیت:** high

**عنوان:** لیورپول در آستانه جذب وینگر برزیلی

لیورپول وارد مذاکرات پیشرفته برای جذب مهاجم کناری ۲۲ ساله برزیلی شده است. سرخ‌ها آماده‌اند قبل از روز پایانی پنجره نقل‌وانتقالات، مبلغ آزادسازی ۵۲ میلیون پوندی او را فعال کنند.

شرایط شخصی مشکلی ندارد؛ بازیکن با قراردادی پنج‌ساله به ارزش حدود ۱۴۰ هزار پوند در هفته به علاوه ۸ میلیون پوند مبالغ متغیر وابسته به تعداد بازی‌ها و صعود به لیگ قهرمانان موافقت کرده است. همچنین بند فروش مجدد ۱۵ درصدی به درخواست باشگاه فعلی او در قرارداد گنجانده شده است.

آرنه اسلوت از پیش‌فصل به دنبال یک مهاجم کناری بود، چرا که پس از مصدومیت همسترینگ محمد صلاح و غیبت شش‌هفته‌ای او، در این پست با کمبود مواجه شده بود. سرمربی هلندی جمعه به خبرنگاران گفت: «نیازی به عجله در بازار نداریم، اما اگر گزینه مناسب وجود داشته باشد، باشگاه دیدگاه مرا می‌داند.»

تست پزشکی برای دوشنبه در مرکز تمرین آکسا برنامه‌ریزی شده است.

`تگ‌ها: نقل‌وانتقالات ، لیورپول ، آرنه اسلوت ، محمد صلاح`

✅ هیچ ایراد خودکاری پیدا نشد.

## opencode-deepseek

❌ خطا: `litellm.Timeout: APITimeoutError - Request timed out. Error_str: Request timed out.`

## opencode-ling

❌ خروجی نامعتبر

## ling-openrouter

❌ خروجی نامعتبر

## gemini-flash
**امتیاز:** 10/10 &nbsp;|&nbsp; **زمان:** 12.0s &nbsp;|&nbsp; **طول:** 800 کاراکتر &nbsp;|&nbsp; **اهمیت:** high

**عنوان:** لیورپول در آستانه خرید ۵۲ میلیون پوندی؛ مذاکرات پیشرفته برای وینگر برزیلی

🔴 اختصاصی: لیورپول وارد مذاکرات پیشرفته برای جذب وینگر ۲۲ ساله برزیلی شده است و سرخ‌ها آماده‌اند تا پیش از پایان پنجره نقل‌وانتقالات، شرط فسخ ۵۲ میلیون پوندی او را فعال کنند.

توافق بر سر شرایط شخصی مشکلی ندارد؛ این بازیکن با قراردادی ۵ ساله به ارزش حدود ۱۴۰ هزار پوند در هفته، به همراه ۸ میلیون پوند مبالغ متغیر مرتبط با تعداد بازی‌ها و صعود به لیگ قهرمانان موافقت کرده است. همچنین بنا به درخواست باشگاه فعلی او، بند ۱۵ درصد از فروش بعدی نیز گنجانده شده است.

آرنه اسلوت از پیش‌فصل پیگیر جذب یک وینگر بوده است، به‌ویژه پس از آنکه مصدومیت همسترینگ محمد صلاح او را ۶ هفته دور از میدان‌ها نگه داشت. این سرمربی هلندی روز جمعه به خبرنگاران گفت: «نیازی نیست در بازار دچار عجله شویم، اما اگر گزینه مناسب پیدا شود، باشگاه نظر من را می‌داند.»

تست پزشکی برای روز دوشنبه در مرکز تمرین آکسا برنامه‌ریزی می‌شود.

`تگ‌ها: لیورپول ، نقل_و_انتقالات ، آرنه_اسلوت ، محمد_صلاح`

✅ هیچ ایراد خودکاری پیدا نشد.

## gemini-flash-lite
**امتیاز:** 10/10 &nbsp;|&nbsp; **زمان:** 8.9s &nbsp;|&nbsp; **طول:** 797 کاراکتر &nbsp;|&nbsp; **اهمیت:** high

**عنوان:** مذاکرات پیشرفته لیورپول برای جذب وینگر برزیلی

🔴 انحصاری: لیورپول وارد مذاکرات پیشرفته‌ای برای جذب وینگر ۲۲ ساله برزیلی شده و سرخ‌ها آماده‌اند تا پیش از روز پایانی نقل‌وانتقالات، شرط فسخ ۵۲ میلیون پوندی او را فعال کنند.

شرایط شخصی مشکلی ندارد و این بازیکن از پیش با قراردادی پنج‌ساله به ارزش حدود ۱۴۰ هزار پوند در هفته، به همراه ۸ میلیون پوند مبالغ متغیر وابسته به تعداد بازی‌ها و کسب سهمیه لیگ قهرمانان موافقت کرده است. همچنین با درخواست باشگاه فعلی او، بند ۱۵ درصد سهم از فروش آینده نیز در قرارداد گنجانده شده است.

آرنه اسلوت از زمان پیش‌فصل به دنبال جذب یک مهاجم کناری بوده است، چرا که پس از مصدومیت همسترینگ محمد صلاح که او را برای شش هفته دور نگه داشته، دست تیم خالی مانده است. این مربی هلندی روز جمعه به خبرنگاران گفت: «ما نباید در بازار نقل‌وانتقالات دچار استرس شویم، اما اگر گزینه مناسبی وجود داشته باشد، باشگاه از افکار من مطلع است.»

`تگ‌ها: نقل‌وانتقالات ، لیورپول ، آرنه اسلوت`

✅ هیچ ایراد خودکاری پیدا نشد.

## groq-qwen

❌ خروجی نامعتبر

## nemotron-super
**امتیاز:** 4/10 &nbsp;|&nbsp; **زمان:** 52.8s &nbsp;|&nbsp; **طول:** 3 کاراکتر &nbsp;|&nbsp; **اهمیت:** high

**عنوان:** ...

...

`تگ‌ها: ...`

**ایرادها:**
- ❌ جا افتاد: مبلغ شرط فسخ ۵۲ میلیون
- ❌ جا افتاد: سن ۲۲ سال
- ❌ جا افتاد: نام لیورپول
- ❌ جا افتاد: نام آرنه اسلوت
- ❌ جا افتاد: نام صلاح
- ⚠️ متن خیلی کوتاه است (3 کاراکتر) — محتوا حذف شده؟

## groq
**امتیاز:** 10/10 &nbsp;|&nbsp; **زمان:** 2.5s &nbsp;|&nbsp; **طول:** 819 کاراکتر &nbsp;|&nbsp; **اهمیت:** high

**عنوان:** لیورپول نزدیک به توافق برای امضای قرارداد

لیورپول وارد مذاکرات پیشرفته برای امضای قرارداد با وینگر ۲۲ ساله برزیلی شده است. سرخ‌ها آماده‌اند تا قبل از روز آخر پنجره نقل‌وانتقالات، شرط آزادسازی ۵۲ میلیون پوندی او را فعال کنند. شرایط شخصی هیچ مشکلی ایجاد نمی‌کند، زیرا بازیکن قبلاً توافق ۵ ساله‌ای را با حقوق هفته‌ای حدود ۱۴۰ هزار پوند، به علاوه ۸ میلیون پوند در مبالغ متغیر بسته به حضور در بازی‌ها و صعود به لیگ قهرمانان، امضا کرده است. همچنین ۱۵ درصد از مبلغ فروش بعدی در قرارداد گنجانده شده است که به درخواست باشگاه فعل
…(truncated to 6000 chars)
<!-- samemind:project:end -->
