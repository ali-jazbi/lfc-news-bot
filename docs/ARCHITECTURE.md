# Architecture

## Overview
LFC News Bot is a Python polling service that aggregates Liverpool FC news from multiple sources, translates it to Persian, scores it for relevance/duplication, and publishes it to a Telegram channel after admin approval (semi-automatic mode).

## High-level pipeline
1. **Fetch** — pull raw items from sources:
   - `sources/lfc_official.py` — official LFC RSS/site feed.
   - `sources/twitter.py` — configured list of Twitter/X accounts via Nitter mirrors + RSS fallback, with per-account cooldown and rotating base URLs.
   - `sources/romano.py` — legacy Fabrizio Romano-specific feed checker (candidate for retirement, see DECISIONS.md).
2. **Normalize** — every source returns a common item dict: `title`, `text`, `url`, `image`, `source_tag` (display name), `handle`, `published_at`.
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

## External dependencies
- Telegram Bot API (bot token, admin group, public channel).
- Nitter mirror instances (unofficial, can go down — see THREAT_MODEL.md).
- LLM providers for translation (opencode endpoints, Groq).
- No database server — state is local (SQLite/JSON via `db.py`), so the deployment target must have persistent disk if history should survive restarts.
