# Threat Model & Known Risks

## Data sources are unofficial / fragile
- **Nitter mirrors** used for Twitter/X ingestion are unofficial, community-run instances. They can go offline or rate-limit at any time. Mitigation: multiple base URLs with rotation, per-account cooldown, and RSS fallback — but there is no guarantee of availability; total ingestion failure for a period is possible and should not silently fail without surfacing via `/errors` or `/health`.
- **Official LFC feed** is comparatively stable but still a single point of failure for that source type.

## Third-party ToS / copyright exposure
- Scraping Nitter/Twitter content, even for a fan news bot, carries some ToS risk from X. Only text/metadata + link is used; no bulk video re-hosting to reduce exposure (see DECISIONS.md).
- Paywalled articles (The Athletic, etc.) are never scraped for full text — only the source's own public tweet/summary + a link is used, to avoid copyright/ToS violations.
- Instagram is intentionally not integrated because reliable methods require using a real personal/business account's login for scraping, which risks that account being banned and violates Instagram's ToS.

## Secrets & credentials
- `.env` holds the Telegram bot token, admin chat ID, channel ID, and LLM API keys. This file must never be committed to a public repository or shared in screenshots/logs.
- If deploying to any third-party host (see RELEASE_POLICY.md), secrets must be set via that platform's secret/environment variable manager, not hardcoded into the repo.

## Availability / operational risk
- The bot is a single long-running process with local file-based state (`db.py`). If the host restarts or the disk is wiped (common on some free hosting tiers), de-duplication history and account cooldown state are lost, which can cause temporary re-posting of recently-seen items or a burst of requests against sources.
- No automatic alerting exists yet beyond the `/health` and `/errors` bot commands — someone has to actively check them. Telegram delivery failures (e.g. the "group upgraded to a supergroup" error) can silently stop all posting until a human notices and fixes the chat ID.

## Translation quality risk
- LLM-based translation can occasionally mistranslate names, scores, or nuance. This is the main reason the admin-approval step exists before anything reaches the public channel — do not remove that step without a stronger automated quality check in place.

## Abuse / misuse risk
- Because the bot posts to a public channel, a bug that bypasses the admin-approval step (e.g. a future "auto-publish" mode) could post an untranslated, mistranslated, or duplicate item at scale. Any future auto-publish feature should keep a kill switch and rate limit.
