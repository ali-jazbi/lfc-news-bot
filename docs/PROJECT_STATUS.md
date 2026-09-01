# Project Status

_Last updated: reflects state as of this documentation pass. Update this file whenever a milestone lands or a known issue is resolved._

## Mode
Running in **test / semi-automatic mode**: bot drafts posts and sends them to an admin Telegram group for manual approval before anything reaches the public channel.

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
