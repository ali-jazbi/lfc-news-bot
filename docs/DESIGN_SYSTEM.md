# Message "Design System"

This project has no visual UI (it's a backend bot), so "design system" here means the consistent rules for how every outgoing Telegram message should look and read. Keep these consistent whenever you touch `formatter.py` or the message templates.

## Structure (see TEMPLATE_GUIDE.md for the full breakdown)
1. Title
2. Body/summary
3. Source attribution (display name + handle)
4. Similarity score (admin draft only)
5. Original link
6. Cover image (when available)
7. Action buttons (admin draft only): Publish / Reject / Re-translate

## Naming consistency
- Twitter/X sources are always shown with their real English display name (e.g. "Fabrizio Romano"), never a Persian transliteration and never just the raw handle. The mapping lives in `TWITTER_NAMES` in `config.py`.
- Club/player/competition names use the `glossary.json` Persian spelling everywhere, so the same entity isn't spelled two different ways across posts.

## Numbers & formatting
- Similarity/duplicate scores are shown as whole-number percentages (e.g. "91%"), never long decimals.
- Dates/times shown to admins or in logs should be human-readable, not raw timestamps, where practical.

## Failure-mode formatting
- If an image can't be attached (e.g. Telegram API error), the bot must still deliver the text content rather than silently failing — always fall back to a text-only message.
- If translation fails through the entire fallback chain, do not publish untranslated/garbled text silently; surface the failure via `/errors` so an admin can investigate.
