# Implementation evidence — 2026-10-04

## Scope and validation

Implemented the durable SQLite ingestion/queue, atomic SourceBatch checkpoints, account re-polling without suspension, separate translation/send retry stages, conservative ordinary-code editorial policy, independent Persian translation quality review, long text handling, online name suggestions and admin approval. No changes to ai/, hermes_skills/, sources/fxembed.py or sources/xscrape.py (verified by git diff). Public posting still uses the existing administrator approval path.

Final test command: `python -m pytest tests -q`. Latest verified run: **289 passed, 3 feedparser deprecation warnings**. Final run after moving background-name refresh into the shared entry point: **289 passed in 37.73 seconds**, with the same three deprecation warnings. `git diff --check` passed. Tests isolate SQLite and disable real userbot video networking by default.

Targeted scenarios include 60 received items with five-item cycle capacity, exact duplicates at the front, fairness between accounts, transaction rollback, restart, retry exhaustion/manual reset, cleanup preservation, malformed first-model fallback, short Persian, small amounts/negation, paragraph chunk retry, unknown name cache/approval, HTML/entity/emoji preservation and failed continuation detection.

## Backup and migration evidence

Explicit pre-change backup: data/backups/20261003T094009Z (SQLite native backup and state copies). Automatic pre-queue and pre-cooldown backups are retained. Local migration completed: discovered=3, new=1, published=1, sent_admin=21. Three legacy `translation chain failed` rows were returned to discovered. Existing admin callback keys were preserved.

## Persian evaluation evidence

Dataset: evaluation/translation_golden.json contains 30 synthetic reference examples. Offline quality check: all 30 references pass. These checks do not establish human fluency. Online existing-provider evaluation: Qwen produced 3 valid translations with no automatic fidelity issues, then rate limited. The other text endpoints immediately rate limited. A configured Whisper endpoint rejected chat requests and is now excluded from translation. The preference in evaluation/provider_order.json is provisional, restricted to already configured providers; a full 30-example live comparison is outstanding. Raw non-secret results are retained locally under evaluation/results/.

## External acceptance limitations

An explicitly labelled technical message was attempted only in the configured administrator group. Telegram returned HTTP 404; the message was not delivered. No public channel post was attempted. Real-group delivery acceptance remains outstanding. The official roster returned HTTP 200 in one probe but other attempts timed out during TLS negotiation; the retained-cache and unavailable-network paths pass tests. No TLS verification bypass was added.

## Graph evidence and limits

The full project graph includes structural AST extraction and semantic documentation/template/image extraction. Existing agent modules are mapped as project content, but were not modified or invoked by the independent implementation. graph.html, graph.json, GRAPH_REPORT.md and diagnostics.json are retained. Structural extraction cannot resolve every dynamic/external call: the diagnostics explicitly include dangling endpoints and collapsed parallel relations. The graph is an architecture aid rather than a runtime completeness proof. Semantic token counts are estimates from the one extractor that reported them; the other extractors did not report usage.

## Delivery limitation

All received normalized news remains traceable in a stored state. Telegram multi-message delivery is not transactional: if a continuation fails after earlier parts succeed, a later retry may repeat those earlier parts. The item remains retryable/failed with its full translation, rather than being marked delivered or truncated.
