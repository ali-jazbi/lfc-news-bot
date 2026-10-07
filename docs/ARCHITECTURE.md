# Architecture

## Overview
LFC News Bot is a Python polling service that aggregates Liverpool FC news from multiple sources, translates it to Persian, scores it for relevance/duplication, and publishes it to a Telegram channel after admin approval (semi-automatic mode).

## High-level pipeline
0. **Hermes AI Editor (optional, HERMES_ENABLED=true)** — after dedup, each item
   passes through the editorial layer before translation: relevance/content-type/
   importance/decision (`ai/editor.py`), verification with web evidence
   (`ai/verifier.py` via `ai/editor.py`), translation QC with channel style
   examples (`ai/quality_control.py`), and image selection (`ai/image_selector.py`).
   All AI output is schema-validated (`ai/schemas.py`); if Hermes is unavailable
   it falls back to the direct LLM chain, then to deterministic keyword/source
   rules. Python remains the backend — Hermes only reasons.
1. **Fetch** — pull raw items from sources:
   - `sources/lfc_official.py` — official LFC RSS/site feed.
   - `sources/twitter.py` — the 29 configured Twitter/X accounts. Which upstream
     is used is chosen by `TWITTER_MODE`:
     - `fxembed` (**recommended**) — FxEmbed/FxTwitter public API v2
       (`sources/fxembed.py`): free, no API key, no cookies/login.
     - `xscrape` — direct x.com HTML scraping (`sources/xscrape.py`). **Dead
       since Sep 2026**: x.com no longer embeds tweet data (`relayRecords`/
       `TBirdData`) in the initial HTML.
     - `classic` — Nitter mirrors + RSS fallback. Legacy: mirrors are dead.
   - `sources/romano.py` — legacy Fabrizio Romano-specific feed checker (candidate for retirement, see DECISIONS.md).
2. **Normalize** — every source returns a common item dict: `title`, `text`, `url`, `image`, `source_tag` (display name), `handle`, `published_at`.
   Twitter-compatible sources (`xscrape`, `fxembed`) return a shared *entry*
   contract (`title, link, summary, image, published` plus the `_xscrape_media`
   / `_xscrape_quoted` side-channels) so the rest of the pipeline — filters,
   `_attach_media`, `_entries_to_items`, formatter — is source-agnostic.
3. **De-duplicate / score** — `channel_guard.py` computes a similarity score against recently-sent items (stored in `db.py`) to avoid re-posting the same story twice. Items above a similarity threshold are suppressed or flagged.
4. **Translate** — `translate.py` runs a fallback chain of translation providers (see "Translation Chain" below) to produce Persian text while preserving names/entities via `glossary.json`.
5. **Format** — `formatter.py` builds the final Telegram message (title, body, source tag, similarity %, buttons) using the channel post template.
6. **Review (admin group)** — `main.py` sends a draft with inline buttons (publish / reject / re-translate) to the admin chat (`ADMIN_CHAT_ID`) for a human check before it goes to the public channel.
7. **Publish** — on admin approval, `telegram_api.py` sends the final post (photo + caption, or text-only fallback) to the public channel (`CHANNEL_ID` / `CHANNEL_USERNAME`).
8. **Persist state** — `db.py` stores sent-item history (for de-dup) and per-account cooldown/error state so restarts don't reprocess or hammer failing sources.

## Translation chain
Order of attempts, controlled by `TRANSLATE_ORDER` in `.env`/`config.py`:
1. `opencode-deepseek` (primary LLM)
2. `opencode-ling` (secondary LLM)
3. `groq` (tertiary LLM, different provider for redundancy)
4. `deep-translator` (non-LLM fallback, e.g. Google Translate wrapper) — always-available last resort

Each step is tried in order; the first that returns a valid, non-empty translation wins. `glossary.json` maps proper nouns/club terms to fixed Persian equivalents so translation stays consistent across providers.

## Key files
| File | Responsibility |
|---|---|
| `main.py` | Orchestrates the polling loop, Telegram command handlers (`/start /help /id /status /sample /check /health /errors`), and the admin approval flow. |
| `config.py` | All tunable settings: thresholds, timeouts, Twitter handle → display-name map (`TWITTER_NAMES`), env var parsing. |
| `sources/*.py` | One module per data source, each exposing a `fetch()`-style function returning normalized items. |
| `translate.py` | Translation fallback chain + glossary application. |
| `formatter.py` | Builds the Markdown/HTML caption sent to Telegram, including similarity badge and source attribution. |
| `channel_guard.py` | Duplicate/similarity detection against post history. |
| `telegram_api.py` | Thin wrapper around Telegram Bot API calls (sendMessage, sendPhoto, getUpdates, download/upload helpers). |
| `db.py` | Lightweight local persistence (sent history, cooldowns, error counters). |
| `health.py` / `doctor.py` | Self-check utilities used by `/health` and manual diagnostics. |
| `get_chat_id.py` | One-off helper to discover a chat's numeric Telegram ID (needed again whenever a group is upgraded to a supergroup). |

## Runtime model
The bot runs as a single long-lived Python process using Telegram long-polling (`getUpdates`), on a fixed interval loop (fetch → process → sleep). It does not require a public HTTP endpoint/webhook. This means hosting only needs outbound internet access and a process that is allowed to run continuously (see RELEASE_POLICY.md for hosting options).

### News drafts and full articles (verified 2026-10-07)

- Automatic collection follows `main()` → `poller_loop()` → `run_cycle()` →
  `collect()` → SQLite ingestion/policy/queue → `process_item()` →
  `_process_item_internal()` → admin draft. All enabled polling sources use
  this news path; `run_cycle()` does not invoke `article_pipeline`.
- Manually pasted tweets and official LFC article links also use `process_item()`
  with `force=True`, after `_handle_tweet_link()` or `_handle_lfc_link()` extracts
  an item. Official LFC news works independently of `ENABLE_ARTICLES`.
- Other manually pasted article URLs use `_handle_article_link()` only when
  `ENABLE_ARTICLES=true`. Its `article_pipeline.run()` → `process_article()`
  flow archives/extracts the full article, translates it, publishes a Telegraph
  page, and sends its link to the admin chat. It uses `article_cache`, rather
  than the news queue and draft approval buttons, and also has a standalone CLI.
- Both paths already share `translate.translate()`; the article `_translate()`
  helper is an async thread wrapper. Their handlers can run concurrently, but
  automatic polling does not process each news item through both pipelines.
  Further unification requires separate approval; these are different outputs.

## External dependencies
- Telegram Bot API (bot token, admin group, public channel).
- **FxEmbed/FxTwitter public API** (`api.fxtwitter.com`) — free, key-less, cookie-less
  source for the 29 Twitter/X accounts (`TWITTER_MODE=fxembed`). Rate limit 1000
  req/min per IP. Self-hosting the same software is the escape hatch (see docs.fxembed.com).
- Nitter mirror instances — **legacy/unreliable**, kept only as a compatibility path
  (`TWITTER_MODE=classic`) and as the explicit-warning last resort of `xscrape`.
- LLM providers for translation (opencode endpoints, Groq).
- No database server — state is local (SQLite/JSON via `db.py`), so the deployment target must have persistent disk if history should survive restarts.
