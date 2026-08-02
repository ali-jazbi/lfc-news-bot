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
