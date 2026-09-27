# Project Status

_Last updated: reflects state as of this documentation pass. Update this file whenever a milestone lands or a known issue is resolved._

## Mode
Running in **test / semi-automatic mode**: bot drafts posts and sends them to an admin Telegram group for manual approval before anything reaches the public channel.

## 2026-09-27 — Twitter source revived: `TWITTER_MODE=fxembed`
- **`xscrape` died quietly (structural change on X's side).** Live probing of all
  29 accounts: some requests get Cloudflare `403` with body `IPv6` (network/IP),
  the rest return `HTTP 200` with 164–192 KB of real HTML **but no `relayRecords`
  and no `TBirdData`** — X stopped embedding tweet data in the initial HTML, so
  `extract_relay_script()` always returns `None`. The page is now a JS shell that
  pulls data from X's internal GraphQL API. Login/cookies (`auth_token`, `ct0`,
  `cf_clearance`) made no difference.
- **New source `sources/fxembed.py`** — FxEmbed/FxTwitter public API v2
  (`https://api.fxtwitter.com`): free, **no API key, no cookies, no login**
  (official OpenAPI + docs). Maps responses to the *same* entry contract used by
  Nitter/xscrape (`title, link, summary, image, published` +
  `_xscrape_media`/`_xscrape_quoted`), so `translate.py`, `formatter.py`, the
  Telegram logic and `main.py` were **not touched**.
- **Live result (real requests, from the bot's own path):** `29 accounts → 27 ok
  / 2 failed = 93.1%`, 524 tweets, 24 accounts with media, 11 with video, 23 with
  quotes, ~5s average latency per account. The 2 failures (`@AnfieldSector`,
  `@Anfieldmedia_`) are **suspended on X** (`User is suspended`) — no source can
  serve them.
- **Two operational findings baked into the code:** the API sometimes drops
  connections without an HTTP code (`RemoteDisconnected`/`SSLError`) → retries
  with backoff, never raises; and accounts with no original posts return `404`
  on the default timeline (e.g. `@LiverpoolFF`, `@mnstr_mntlt`) → one retry with
  `with_replies=1`, filtered to the account's own posts/retweets (this lifted the
  success rate from 25/29 = 86% to 27/29 = 93%).
- **Incremental polling:** `GET .../statuses?since=<unix>` returns `204 No Content`
  when nothing is newer; per-account last-seen timestamps are stored in
  `data/twitter_state.json` (`fxembed_since`) with a 15-minute overlap so a tweet
  that failed downstream is seen again next cycle. Config: `FXEMBED_USE_SINCE`,
  `FXEMBED_SINCE_OVERLAP_SECONDS`.
- **Fallbacks:** `XSCRAPE_FALLBACK_CLASSIC` kept (default unchanged) but now logs
  an explicit warning that classic/Nitter is *no longer a reliable source*;
  `TWITTER_MODE=classic` and `TWITTER_MODE=xscrape` still work and are documented
  as legacy/dead. The new mode deliberately does **not** fall back to Nitter.
- **Tests:** `tests/test_fxembed.py` (28 network-free tests, FAIL→FIX→PASS);
  full suite **236 passed**, zero regressions. Live harness:
  `scripts/manual_tests/test_fxembed.py`; raw probes:
  `scripts/diagnostics/probe_sources.py`.
- **GraphQL was NOT needed** (recorded as the next fallback if FxEmbed ever
  becomes unavailable; self-hosting FxEmbed is the preferred intermediate step).

## 2026-09-27 (review round) — production hardening
- **Real cursor pagination in the polling path**: `since` alone was not enough — if a
  window held more than `count=20` posts (long downtime, deadline day) the rest were
  silently lost. `_own_statuses_paged()` now follows `cursor.bottom` until the page is
  empty, capped by `FXEMBED_MAX_PAGES` (default 3 ⇒ hard cap 60 tweets/account), with
  id de-duplication and a request-count cap so a non-advancing cursor can never loop.
  Verified live: cycle 1 = 36 tweets, cycle 2 = 115 tweets via pagination, **0 lost**.
- **Learned semantics:** `since` is a *poll signal*, not a filter — it returns `204`
  when nothing is strictly newer, otherwise the normal page. That is exactly why the
  15-minute overlap exists (next cycle re-sees the latest tweets; DB removes dupes).
- **Removed the fake throttle**: `time.sleep(INTER_ACCOUNT_DELAY)` after submitting all
  futures did nothing; the only real throttle is `FXEMBED_WORKERS`. A test now fails
  the fetch path if it ever sleeps again. Rate-limit comment corrected to the
  documented **1000 requests/minute per IP**.
- **Partial-failure tests added**: state (`fxembed_since`) is written only for accounts
  that returned data, a failed account is retried next cycle *without* `since`, and a
  partial failure never trips `fxembed_dead_cycle` (that counter is for "all accounts
  empty" only). Successful accounts still enter the pipeline in the same cycle.
- **Suspended/deleted accounts now cool down 24h**: `fxembed.suspension_reason()`
  (called only when an account yields nothing) returns `suspended`/`not_found`, which
  is stored in `data/twitter_state.json → fxembed_cooldown`; those accounts are not
  requested again until it expires. Verified live: `@AnfieldSector` → `suspended`,
  `@LiverpoolFF` → 20 tweets (with_replies) → 60 in the next cycle.
- **Tests:** `tests/test_fxembed.py` 28 → **40**; full suite **248 passed**. Live
  29-account run after the fixes: **27/29 = 93.1%**, 528 tweets (25 with media,
  12 with video, 23 with quotes).

## Completed
- Multi-source ingestion: official LFC feed, 29 curated Twitter/X accounts (via Nitter + RSS fallback), legacy Romano feed checker.
- **Twitter reliability (2026-08):** 429-safe polling (staggered rotation, 4 workers, inter-account delay); a 429 no longer triggers a 30-min account cooldown — rate-limited accounts are retried next cycle so news isn't missed.
- **Multi-image albums (2026-08):** extracts all of a tweet's OWN photos from the Nitter summary (before the first `<blockquote>`, excluding card/avatar/banner) into `item["images"]` for Telegram media-group albums.
- **Video delivery (2026-08):** detects video tweets via the Nitter poster, resolves the direct `video.twimg.com/...mp4` via fxtwitter (fallback vxtwitter), sends via Telegram `sendVideo` (URL first, download-and-upload fallback).
- Duplicate/similarity detection (`channel_guard.py`) with a similarity percentage shown to the admin.
- Multi-provider translation fallback chain with a glossary for consistent proper-noun translation.
- Telegram admin workflow: draft preview, inline buttons (publish / reject / re-translate), and public-channel publishing with photo-or-text-fallback handling.
- Bot commands: `/start /help /id /status /sample /check /health /errors`.
- Display-name mapping for Twitter sources switched from Persian transliteration to real English names per user feedback.
- Percentage formatting fix so similarity shows as a clean integer (e.g. "91%") instead of a long float.
- Diagnosed and documented the Telegram "group upgraded to supergroup" failure mode and the fix (`get_chat_id.py` + updating `ADMIN_CHAT_ID`).

## 2026-08-31 — hashtags, multi-source attribution, multi-video
- **Hashtags removed from translated output**: the LLM and Google translator
  both pass `#hashtags` through (e.g. `#AFC #Arsenal #FPLCommunity`), plus the
  Google path sometimes emits a literal `\x3C` artifact. `_strip_hashtags()` in
  `translate.py` is now applied to title+body on both paths. Source-side
  relevance is untouched — tweets with `#LFC` / `#Liverpool` hashtags are still
  detected as relevant (regression-locked with tests).
- **Multi-source attribution**: `detect_original_source` only looked at a
  mention at the very END of the text (so `@Santi_J_FM` after an emoji was
  missed). New `detect_original_sources()` scans the WHOLE text for `@handle`,
  `_handle` (mid-text convention like «به نقل از _pauljoyce») and nitter
  mention links, dedupes, drops the author's own handle, and returns ALL of
  them: first = primary source (channel), rest listed in the admin preview
  note («منابع دیگر»). Approved strategy: any mention counts — the admin
  preview protects against false positives.
- **Multi-video tweets**: `@twittervid_bot` sends every video of a tweet but
  the userbot forwarder only captured the FIRST video message. It now collects
  all video replies in a short grace window and forwards them all (caption on
  the first). Local fallback path also sends every video from
  `item["video_urls"]` (new, capped by `TWITTER_VIDEO_MAX`, default 4).

## 2026-08-31 — translation parse hardening
- The qwen provider (opencode) started appending an HTML metadata comment
  (`<!-- qwen_metadata: {...} -->`) after the JSON — its closing brace broke
  `_extract_json` (rfind hit the metadata, not the main JSON), so every valid
  translation was rejected (خروجی نامعتبر). Parser now strips trailing HTML
  comments and falls back to a balanced-brace extractor. 5 new tests; 166 pass.

## 2026-08-31 — xscrape news-loss fixes (4 bugs)
- **Keyword filter too narrow**: `ROMANO_KEYWORDS` expanded to the current
  squad + manager (Iraola replaced the stale `slot`) + common club names;
  `_is_relevant` now also checks the quoted-tweet text (short caption like
  "Here we go 🔴" + Liverpool quote is no longer rejected). NOTE: this list
  is perishable — review it before every transfer window (see config.py).
- **`[:3]` cap in the filter loop**: only the first 3 tweets per account were
  checked while 8 were scraped — busy days dropped fresh tweets. Now
  configurable via `TWEETS_CHECKED_PER_ACCOUNT_PER_CYCLE` (default 8), in
  both `_fetch_xscrape` and `_fetch_classic`.
- **`scrape_user` had no retry**: switched from the single-shot cookie
  `_session` path to the shared retry/cookie-free `_fetch_html` used by
  `fetch_tweet`. Live: 28/29 accounts answered (single-shot lost ~50% to 403).
- **Long-form (X Premium) tweets truncated**: relay `note_tweet` block is now
  parsed (`extract_note_tweet_text`) and preferred over the truncated legacy
  `full_text` when longer — verified live on a real 1400+ char tweet.
- Tests: 11 new network-free tests (161 total pass).

## 2026-08 AI newsroom upgrade
- **Hermes Agent integration** (v0.18.2): editorial layer with 3-tier analysis,
  web-evidence verification, translation QC with channel style, image selection.
  Gated behind `HERMES_ENABLED` (default off → zero behavior change).
- **Source health + concurrent collection**: per-source healthy/degraded/failed
  with backoff; one dead source no longer blocks the cycle.
- **News state machine**: new statuses + error/retry_count/last_attempt_at;
  Telegram send failures → retry_pending → retried each cycle → failed (with
  error) after MAX_SEND_RETRIES. Nothing silently lost.
- **Video pipeline** (`media.py`): download/validate/transcode/thumbnail on disk
  with named failure states.
- **Human feedback loop**: admin approve/retranslate actions stored vs AI decision.
- **MCP server** (`lfc_mcp_server.py`, 10 tools) + 5 Hermes skills (editor,
  verifier, translator, image-selector, quality-control) — installed & enabled.
- **Tests**: 75 pytest tests (sources/dedup/AI/translation/image/video/telegram/
  state/e2e). Evaluation on real DB: see `docs/EVALUATION_REPORT.md`.

## In progress / pending
- **Watch** live for 429s on `nitter.net` under the new staggered polling — should be near-zero; if they persist, lower `TWITTER_WORKERS` or raise `TWITTER_INTER_ACCOUNT_DELAY`.
- Decide on filtering low-value/fluff tweets (e.g. raise minimum word count, or add a phrase blocklist).
- Optional `.env` cleanup: stray leading space in `BOT_TOKEN`, mis-keyed `LLM4_*`/`LLM5_*` block, redundant `TWITTER_ACCOUNTS=` line.
- Open question: whether to raise `CHANNEL_GUARD_THRESHOLD` (suggested 88) to reduce false-positive duplicate suppression.

## Explicitly out of scope for now
- Instagram ingestion (no safe/stable free method available).
- Full-text republishing of paywalled articles (e.g. The Athletic) — tweet/summary + link only.

## How to pick this up
Read `ARCHITECTURE.md` for how the system fits together, `DECISIONS.md` for why it's built this way, and `AGENT_WORKFLOW.md` for how to safely make changes.
