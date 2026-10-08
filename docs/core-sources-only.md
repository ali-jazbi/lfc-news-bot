# Temporary production source restriction — 2026-10-08

No production `.env` edit is required. Install the code change and restart the
service. The existing `ENABLE_LFC=true` and `TWITTER_MODE=fxembed` settings stay
as they are. `CORE_SOURCES_ONLY` defaults to true and the official Google fallback
defaults to false when their new keys are absent. Core mode also overrides old
enabled settings for optional inputs.

The following block documents the effective settings; copying it into `.env`
is optional, not a deployment requirement:

```env
CORE_SOURCES_ONLY=true
ENABLE_TWITTER=true
TWITTER_MODE=fxembed
ENABLE_LFC=true
ENABLE_LFC_GOOGLE_FALLBACK=false
ENABLE_OUTLET_RSS=false
OUTLET_RSS_SOURCES=
ENABLE_NEWS_SEARCH=false
ENABLE_ROMANO=false
ENABLE_BLUESKY=false
ENABLE_ARTICLES=false
```

Keep the existing Twitter account list, translation settings and Twitter media
settings. No secrets are needed in this document.

## Reported post and root cause

The supplied draft shows a Google News logo, a player-name-only title/body and
the source label `[Liverpool FC]`. Its source URL is `news.google.com/rss/articles/…`.

`sources/lfc_official.py::_google_fallback()` assigned that official-club label
to Google News RSS results. `_listing_summaries()` invoked it when the official
listing request failed **or** contained no parseable news links. The RSS summary
fell back to its title when no useful summary existed. `media_preview.enrich()`
then fetched the aggregator page's preview image, yielding the Google News logo.
This route did not check `ENABLE_NEWS_SEARCH` or `ENABLE_OUTLET_RSS`.

Relevant history:

- `b0a9f7f` (2026-10-04): introduced persistent ingestion and listing summaries
  for `ENABLE_ARTICLES=false`, including the independent Google fallback.
- `6a0343f` (2026-10-05): added independent news discovery.
- `5cf7ee6` (2026-10-07): added linked-page media preview enrichment.
- `d09a4b4` (2026-10-07): improved stale-live-news and translator diagnostic
  filtering, without removing this fallback.
- `38aa07c` and `40b919d` (2026-10-07): changed invalid-QC handling and provider
  request options. These did not disable upstream Google News ingestion.

A live official listing also exposed a second extractor bug: current article
cards have an empty overlay anchor, with the heading/image/date as siblings in
`<article>`. The old parser skipped those real articles and returned navigation
labels such as `Men` from `/news/listing/…`. It now reads the containing article
card (or its accessible link title) and rejects category/listing URLs, including
such URLs already stored in the queue.

`.env.example` is not read by `config.py`; previous optional-source defaults in
`config.py` were enabled. `load_dotenv()` loads `.env` with `override=False`, so
an existing environment variable takes precedence over the file. Even correctly
disabled fetchers did not previously stop news already stored in SQLite.

## Behavior after the fix

- Core mode overrides even stale `true` values for optional sources.
- Official-site failure yields no official drafts instead of Google RSS.
- Real Twitter status URLs and direct official news/article URLs stay eligible.
- Existing non-core queue/send retries are preserved in `source_disabled`.
- Source checks run before grouping, so disabled RSS cannot supply another
  draft's body/image through a new story merge. Old merged text explicitly
  attributed to a non-core URL is blocked too.
- Old disabled draft buttons cannot publish or retranslate that draft.
- Google News URLs cannot supply linked-page preview logos for tweets.
- No messages already delivered to Telegram are deleted by this change.

To revisit optional sources later, set `CORE_SOURCES_ONLY=false` and enable only
the desired inputs. Restoring Google fallback requires its separate explicit
flag. Paused queue items restore their previous stage when the source is allowed.

## Verification

`tests/test_core_sources.py` covers default settings, both official extraction
modes, site failure/unparseable HTML, URL spoofing, optional-source overrides,
backlog/retry restart and restoration, pruning, delivery buttons and Google
preview suppression. Existing source/queue/discovery/media/FxEmbed tests also run.

Live source probing uses an isolated temporary SQLite database and Twitter state,
without calling translation providers or Telegram. It verifies ingestion only;
deployed-server behavior still requires the actual runtime logs and configuration.

Local live observations on 2026-10-08:

- FxEmbed cycle 1: 29 accounts polled, 27 returned data, 510 mapped tweets,
  492 unique items ingested, 27 checkpoint records; about 45 seconds.
- FxEmbed cycle 2 using the stored checkpoints: 29 accounts polled, 13 returned
  data, 506 mapped tweets, 251 additional unique items ingested; about 177 seconds.
  Pagination can return older unseen tweets too, so additional insertions do not
  imply that 251 tweets were just published.
- `AnfieldSector` and `Anfieldmedia_` were empty in the first cycle. Separate
  profile requests exhausted retries with `RemoteDisconnected`; their current
  suspension/deletion status could **not** be confirmed from these requests.
- Current scraper APIs return `[]` for both HTTP 204/no updates and several
  upstream/network failures. Existing account diagnostics therefore cannot fully
  distinguish an empty feed from a broken upstream. This remains a Twitter
  observability issue; these observations do not prove reliable server ingestion.
- Official extraction before the fix returned nine navigation entries, including
  `Men` and `Women`. After the fix it returned twelve direct news articles with
  real titles/images and zero listing/category links.

Translation providers were not called in these live tests. Upstream empty or
player-name-only RSS input explains the reported example; it does not establish
the quality of every other translated post. Full translation/provider tuning and
upstream Twitter reliability work remain separate follow-ups.
