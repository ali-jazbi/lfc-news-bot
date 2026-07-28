# LFC News Bot

An automated Telegram bot that tracks Liverpool FC news in near real time from the official club site and a curated list of trusted Twitter/X journalists, translates it into Persian using a free multi-provider LLM fallback chain, and sends a ready-to-review post (with image) into an admin group. An admin approves it with one tap before it goes out to the public fan channel.

> A Persian version of this README is available at [README.fa.md](README.fa.md).

```
Sources ──> dedup / filter ──> translate (free LLM chain) ──> admin group review
   [Publish | Reject | Re-translate] ──> public channel (manual copy/forward)
```

## Features

- **Multi-source ingestion**: official LFC site + 29 curated Twitter/X accounts (via Nitter mirrors + RSS fallback, with per-account cooldown and automatic mirror rotation).
- **Free translation fallback chain**: tries several free LLM providers in order (with a non-LLM translator as the last resort) so the service keeps working even if one provider is rate-limited or down.
- **Duplicate & similarity detection**: avoids re-sending the same story twice, and warns (rather than blocks) when a story looks similar to something already published on the channel.
- **Human-in-the-loop publishing**: nothing is posted to the public channel automatically — every item is reviewed and approved by an admin in a private group first.
- **Operational tooling**: built-in bot commands (`/status`, `/health`, `/errors`, `/sample`, `/check`) for live diagnostics without needing server access.

## Quick start

### 1. Create the bot and chats
1. In Telegram, talk to `@BotFather` → `/newbot` → copy the bot token.
2. Add the bot to your **admin group** and make it an admin.
3. In that group, send `/id` to get the group's `chat_id` (a negative number).
4. Add the bot to your **public channel** as an admin (with permission to post messages).

### 2. Get free translation API keys
Add one or more provider keys to `.env` (see `.env.example`). If one provider is rate-limited, the bot automatically falls back to the next one in the chain.

### 3. Run it
```bash
cp .env.example .env      # fill in your values
pip install -r requirements.txt

python main.py --once --dry-run   # test: no Telegram calls, prints to terminal
python main.py --once             # test: one real cycle -> admin group
python main.py                    # run continuously
```

Or with Docker:
```bash
docker compose up -d --build
docker compose logs -f
```

## Project structure

| File | Responsibility |
|---|---|
| `main.py` | Main loop: source polling, Telegram long-polling, command/button handlers |
| `config.py` | All settings, loaded from `.env` |
| `db.py` | SQLite storage + duplicate detection (URL hash + title similarity) |
| `sources/lfc_official.py` | Official club site scraper |
| `sources/twitter.py` | Twitter/X ingestion via Nitter mirrors + RSS fallback |
| `sources/romano.py` | Legacy Fabrizio Romano-specific feed checker |
| `translate.py` | Translation fallback chain + glossary enforcement |
| `formatter.py` | Builds the channel/admin message templates and inline buttons |
| `telegram_api.py` | Lightweight Telegram Bot API client |
| `channel_guard.py` | Similarity check against recent public channel posts |
| `glossary.json` | Proper noun / terminology dictionary — expand this for translation quality |
| `docs/` | Deeper technical docs: architecture, decisions log, threat model, deployment guide, and more |

## Output format

```
🔴 News title

Translated Persian body, 2-4 short paragraphs...

[Fabrizio Romano]
@YourChannel
```
🔴 is used for urgent/high-importance news (confirmed transfers, injuries, lineups, official statements) with notification sound; ⚪️ is used for everything else, sent silently.

## Operational notes

- On first run, the bot silently backfills its database with existing items so the admin group isn't spammed with old news (`BOOTSTRAP_SILENT=true`).
- Typical latency is well under the poll interval (`POLL_INTERVAL=60` seconds by default).
- For free always-on hosting options and trade-offs, see [`docs/RELEASE_POLICY.md`](docs/RELEASE_POLICY.md).
- Translation quality depends heavily on the glossary — add any new name/term you see mistranslated to `glossary.json`.
- To add a new source, create a file under `sources/` exposing a `fetch(limit)` function that returns a list of dicts with keys `source, source_tag, url, title, body, image`, then call it from `main.collect()`.

## More documentation

See the [`docs/`](docs) folder for architecture details, past decisions, current project status, known risks, and the deployment guide.
