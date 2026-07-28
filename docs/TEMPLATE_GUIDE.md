# Message Template Guide

Describes the structure of the messages the bot produces, for anyone editing `formatter.py`.

## Admin review draft (sent to the admin group)
- Title (translated to Persian).
- Body/summary (translated to Persian), with proper nouns kept consistent via `glossary.json`.
- Source attribution line: display name (e.g. "Fabrizio Romano") + original handle (e.g. "@FabrizioRomano").
- Similarity/duplicate score shown as a clean integer percentage (e.g. "Similarity 91%").
- Link back to the original source (tweet/article/feed item).
- Cover image, when available (falls back to text-only if the image can't be sent — e.g. during the supergroup-migration bug, see PROJECT_STATUS.md).
- Inline buttons: **Publish** (send as-is to the public channel), **Reject** (discard), **Re-translate** (retry the translation chain for this item).

## Public channel post (sent after admin approval)
- Same title/body/image as the approved draft, minus the admin-only similarity score and buttons.
- Source attribution line is kept so readers know where the news originated.
- Link to the original source is kept for readers who want more detail (especially important since paywalled/video content is never rehosted — see DECISIONS.md).

## Tone & style
- Persian translation should stay close to the literal meaning of transfer/football news — avoid embellishment.
- Club and player names should use the glossary-approved Persian spelling for consistency across posts.
- Keep captions concise; Telegram has a caption length limit for photo messages, so very long translated text should be trimmed/handled gracefully (fall back to text-only message if needed).
