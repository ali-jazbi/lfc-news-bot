# News pipeline migration and operation

The existing scraper transport and upstream endpoints are unchanged. The new ingestion, queue, policy, Persian glossary and quality checks work with HERMES_ENABLED=false. Agent modules are outside this change.

## Durable ingestion

Sources return SourceBatch(items, checkpoints). Every normalized received item is inserted before policy, translation or delivery. SQLite commits payloads and account checkpoints together. A failed transaction commits neither. Previously saved JSON checkpoints are imported once. Empty/suspended/not_found responses do not exclude accounts; legacy account cooldowns are backed up and removed on state load. Upstream source fetch limits and concurrency still apply.

Five is a processing budget, including failed send retry attempts. Excess news remains in SQLite. The oldest discovered item in each source/account group is selected in persistent round-robin order. Restart releases interrupted processing states. Bootstrap no longer silently skips collected news. Similar titles are advisory; distinct URLs retain article identity parameters. Exact published/admin-pending records are blocked. Failed records retain payloads and can be reset manually.

## Retry and migration

Translation and send retries have separate stages. After three failed attempts the item remains failed with its error; /retry KEY resets it, /retry lists the queue. /status reports source counters, queue states and recent failed/rejected reasons. Cleanup preserves all unfinished, failed and admin-pending payloads. The first schema migration backs up an existing database; an explicit pre-change SQLite/JSON backup is also in data/backups/20261003T094009Z. Legacy translation-chain failures re-enter the queue once. Existing callback keys are retained during URL migration.

## Persian translation

Instructions and shared glossary are in the system message; source news is user data. No fixed current-manager identity is injected. Invalid model output tries the next configured text model; speech/embedding models are excluded. Short output is accepted when valid Persian. Deterministic checks cover names, numbers, currencies and negation. A direct configured LLM reviews certainty, attribution and source fidelity, with at most two revisions. Unavailable reviews, unresolved issues and machine fallback are explicitly flagged to the admin. Long articles translate paragraph chunks, checkpoint successful chunks and retry failed pieces. Full translations remain stored; HTML-aware Telegram continuations respect UTF-16 limits. A partially acknowledged multi-message delivery can duplicate already sent parts on retry; Telegram offers no transaction across messages.

## Names and coverage

Official men's roster profile URLs identify people; Wikibase Persian labels and aliases are matched to human/club affiliation. Existing approved spellings take precedence. New candidates or spelling disagreements require /names set ID PersianName approval; evidence is shown by /names. Roster refresh is daily, unknown-name lookups run in the background with positive/negative daily caching. Offline lookup never blocks news. The roster parser keeps the old inventory if the site format changes.

Ordinary Python policy passes ambiguous football material to admin review. Missing keywords, old years in text and watch alone are not rejection rules. Explicit promotion and clearly unrelated coverage are rejected with reasons. Official listing summaries are available even when full articles are disabled. Publication time is retained in payloads; queued news does not expire because of age.

## Evaluation and acceptance

Thirty synthetic English/Persian reference fixtures cover negation, amounts, dates, rumours, attribution and names. Run python scripts/maintenance/evaluate_translation.py for offline checks; --live --limit 30 evaluates configured providers without Telegram or agent calls. evaluation/provider_order.json is a provisional preference from three successful Qwen Persian samples. Other providers hit rate limits; a full thirty-item live fluency comparison remains unverified. Human review remains necessary.

Run python -m pytest tests -q. Integration tests exercise sixty-item ingestion, a five-item budget, duplicate-front batches, fair rotation, transaction rollback/checkpoints, restart, retries, cleanup, invalid-model fallback, long translation, unavailable names and HTML continuations.

The real admin-only technical test received Telegram HTTP 404, so real delivery acceptance is outstanding until the configured bot/API connection works. No public channel test post was sent. Official roster network probes were intermittent (one HTTP 200, other TLS timeouts); offline behavior is covered by tests.
