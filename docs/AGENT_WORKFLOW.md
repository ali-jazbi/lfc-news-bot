# Agent / Contributor Workflow

Guidance for any AI coding agent or human contributor picking up this project.

## Before making changes
1. Read `ARCHITECTURE.md` to understand the pipeline (fetch → dedupe → translate → format → admin review → publish).
2. Read `DECISIONS.md` to understand why certain things are built the way they are (e.g. why there's an admin-approval step, why video/Instagram/paid articles are out of scope).
3. Read `PROJECT_STATUS.md` for what's done, what's pending, and what's explicitly known-broken.
4. Read `THREAT_MODEL.md` before changing anything related to publishing safety, secrets, or scraping behavior.

## Making changes
- Prefer small, targeted edits over rewriting whole files.
- Any change to publishing behavior (e.g. removing the admin-approval step, adding auto-publish) must keep a way to disable/roll back quickly and should not be shipped without explicit user sign-off (see THREAT_MODEL.md — abuse/misuse risk).
- When adding a new content source, follow the existing `sources/*.py` pattern: expose a function that returns normalized item dicts with the same keys used by existing sources (`title`, `text`, `url`, `image`, `source_tag`, `handle`, `published_at`).
- When changing translation behavior, test with `--once --dry-run` first and check `glossary.json` still resolves club-specific terms correctly.
- When adding/removing a Twitter handle, update `TWITTER_NAMES` in `config.py` (English display names only — see DECISIONS.md) and re-verify the handle is live before adding it.
- Keep `.env.example` in sync with any new environment variable you introduce, but never put real secrets in it.

## Testing
- Use `python main.py --once --dry-run` to run a single pass without sending live messages, useful for verifying fetch/translate/format changes.
- Use `get_chat_id.py` whenever a Telegram group's numeric ID is needed or has changed (e.g. after a "group upgraded to supergroup" event).
- Use `/health`, `/status`, `/errors`, `/sample`, `/check` bot commands in the admin chat for live diagnostics.

## Documentation hygiene
- Update `PROJECT_STATUS.md` whenever you complete or discover a pending item.
- Add a new entry to `DECISIONS.md` whenever you make a non-obvious product or architecture choice, especially ones driven by a constraint (free-tier limits, ToS/copyright, API cost) rather than pure preference.
- If you change the public channel post format, update `TEMPLATE_GUIDE.md` to match.
