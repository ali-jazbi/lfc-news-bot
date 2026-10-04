# Graph Report - lfc-news-bot  (2026-10-04)

## Corpus Check
- 155 files · ~102,030 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 7 file(s) not represented in the graph (top: (none) 6, .example 1)

## Summary
- 1712 nodes · 3658 edges · 86 communities (73 shown, 13 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 131 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- telegram_api, names
- formatter, test_edit_formatting
- main,
- editor, test_decision
- test_video, media
- hermes_client, test_verification
- test_outlet_rss_extra, outlet_rss
- config,
- article_pipeline,
- evaluate, install_hermes
- db, test_state
- test_fxembed, twitter
- test_image, image_selector
- hermes_client, test_verification
- test_ai, test_decision
- test_fxembed, fxembed
- test_xscrape, xscrape
- test_qc_fail_closed, test_translation
- test_sources, romano
- lfc_official, base
- translate,
- fxembed, test_fxembed
- 2026-08-31-hashtags-sources-videos, DESIGN_SYSTEM
- test_queue_pipeline, db
- twitter
- test_e2e,
- test_telegram
- userbot_downloader,
- test_xscrape,
- health
- test_independent_translation, translate
- test_fxembed_cycles, check_accounts
- db, main
- test_source_detection, twitter
- xscrape
- db, main
- test_extract_json, translate
- twitter, test_fxembed
- db_prune, probe_fx_contract
- lfc_mcp_server
- channel_guard, check_channel
- test_translate_output, translate
- schemas, test_ai
- _template, index
- source_health, db
- translate, benchmark
- probe_sources
- SKILL, ARTICLE_PIPELINE_PLAN
- conftest,
- conftest, test_e2e
- conftest
- twitter, base
- test_translation, quality_control
- test_fxembed, fxembed
- twitter
- quality_control
- DECISIONS, PROJECT_STATUS
- doctor,
- test_dedup
- test_state,
- test_xscrape, xscrape
- test_twittervid_bot
- test_xscrape, xscrape
- sample_item, test_send
- test_fxembed
- test_xscrape
- test_xscrape
- twitter, base
- test_multi_video
- translate
- twitter
- 2026-08-23-xscrape-feature, 2026-08-25-tweet-link-session
- bluesky
- HERMES_INTEGRATION, SKILL
- test_xscrape,
- .mcp
- twitter
- twitter
- test_fxembed,
- redeploy
- watchdog
- docker-compose
- sample
- _template

## God Nodes (most connected - your core abstractions)
1. `_c()` - 45 edges
2. `NewsAnalysis` - 40 edges
3. `NewsEditor` - 36 edges
4. `VerificationResult` - 30 edges
5. `Telegram` - 30 edges
6. `_Resp` - 30 edges
7. `_patch()` - 30 edges
8. `scrape_user()` - 29 edges
9. `deterministic_analysis()` - 28 edges
10. `TranslationReview` - 28 edges

## Surprising Connections (you probably didn't know these)
- `RSS age filtering keeps unknown dates and bypasses keyword checks` --semantically_similar_to--> `Never silently lose news`  [INFERRED] [semantically similar]
  inbox/2026-09-28-extra-rss-sources.md → docs/DECISIONS.md
- `Durable news pipeline operation` --documents--> `approve()`  [INFERRED]
  docs/NEWS_PIPELINE.md → names.py
- `Durable news pipeline operation` --documents--> `split_html()`  [INFERRED]
  docs/NEWS_PIPELINE.md → telegram_text.py
- `Durable news pipeline operation` --documents--> `_quality_review()`  [INFERRED]
  docs/NEWS_PIPELINE.md → translate.py
- `Durable news pipeline operation` --documents--> `ingest_batch()`  [INFERRED]
  docs/NEWS_PIPELINE.md → db.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Preserving news requires reconciling retry limits, pagination caps, cooldown, and retention** — docs_decisions_never_lose_news, docs_decisions_delivery_retry, docs_project_status_pagination_cap, docs_project_status_source_cooldown, docs_release_policy_retention [INFERRED 0.85]
- **Translation availability, glossary fidelity, and fail-closed quality review** — docs_decisions_translation_fallback, readme_glossary, docs_hermes_integration_qc_fail_closed, hermes_skills_lfc_news_translator_skill_translator, hermes_skills_lfc_news_quality_control_skill_qc [INFERRED 0.85]

## Communities (86 total, 13 thin omitted)

### Community 0 - "telegram_api, names"
Cohesion: 0.05
Nodes (31): _api(), approve(), glossary(), lookup(), refresh(), refresh_unknowns(), remember_unknowns(), report() (+23 more)

### Community 1 - "formatter, test_edit_formatting"
Cohesion: 0.06
Nodes (32): display_name(), build_admin_caption(), build_caption(), build_original_message(), build_original_source_note(), _combined_source_label(), _detect_quote_post(), esc() (+24 more)

### Community 2 - "main, "
Cohesion: 0.07
Nodes (27): _apply_reply_edit(), bot_loop(), _cleanup_status(), collect(), drain_pending_updates(), _entities_to_html(), _entity_to_tag(), _handle_article_link() (+19 more)

### Community 3 - "editor, test_decision"
Cohesion: 0.10
Nodes (23): _blob(), deterministic_analysis(), _handle(), _hard_rules_analysis(), _is_liverpool_relevant(), _is_official(), _is_outdated(), _is_trusted_outlet() (+15 more)

### Community 4 - "test_video, media"
Cohesion: 0.08
Nodes (25): cleanup(), _download(), _ensure_dir(), _ffmpeg(), _ffprobe(), MediaError, _probe(), process() (+17 more)

### Community 5 - "hermes_client, test_verification"
Cohesion: 0.08
Nodes (27): collect_evidence(), _conflicting_evidence(), review_translation(), select_image(), _default_bin(), evidence_is_sufficient(), _image_prompt(), _tier_of_source() (+19 more)

### Community 6 - "test_outlet_rss_extra, outlet_rss"
Cohesion: 0.08
Nodes (27): enabled_source_ids(), fetch(), fetch_extra(), _is_relevant(), _outlet_name(), _team_specific(), _too_old(), _entry() (+19 more)

### Community 7 - "config, "
Cohesion: 0.09
Nodes (7): _float(), _get(), _int(), _list(), _llm_slot(), _pairs(), main()

### Community 8 - "article_pipeline, "
Cohesion: 0.09
Nodes (20): _arch_headers(), archive_url(), author_name(), build_message(), _existing_snapshot(), extract_article(), _get_telegraph_token(), _get_text() (+12 more)

### Community 9 - "evaluate, install_hermes"
Cohesion: 0.09
Nodes (23): hermes_bin(), hermes_home(), install_mcp(), install_skills(), main(), build_report(), _cache_path(), _compare() (+15 more)

### Community 10 - "db, test_state"
Cohesion: 0.08
Nodes (22): article_get(), article_save(), _c(), channel_examples(), get_by_admin_msg(), import_checkpoints(), init(), is_duplicate() (+14 more)

### Community 11 - "test_fxembed, twitter"
Cohesion: 0.09
Nodes (23): item_from_url(), _entry(), _fx_mode(), _quote(), test_cooldown_expires_after_24h(), test_empty_or_suspended_account_is_polled_on_next_cycle(), scrape(), test_failed_account_retried_next_cycle() (+15 more)

### Community 12 - "test_image, image_selector"
Cohesion: 0.11
Nodes (17): NewsEditor, candidate_images(), seen_urls(), select_image(), create_editor(), ImageSelection, news_id_of(), trace() (+9 more)

### Community 13 - "hermes_client, test_verification"
Cohesion: 0.09
Nodes (15): _analysis_prompt(), HermesClient, HermesError, extract_json_object(), VerificationResult, test_verify_fallback_evidence_only_score(), boom(), test_verify_no_evidence_never_verified() (+7 more)

### Community 14 - "test_ai, test_decision"
Cohesion: 0.10
Nodes (23): NewsAnalysis, _editor_with(), test_ai_low_confidence_downgrades_to_review(), test_ai_provider_failure_falls_back(), test_ai_publish_decision(), test_ai_reject_decision(), test_ai_review_decision(), test_ai_speculation_never_auto_publish() (+15 more)

### Community 15 - "test_fxembed, fxembed"
Cohesion: 0.13
Nodes (19): scrape_user(), _page(), fake_get(), _Resp, _status(), test_bad_json_never_raises(), test_count_is_capped_and_sent(), test_grouped_thread_uses_focal_status() (+11 more)

### Community 16 - "test_xscrape, xscrape"
Cohesion: 0.10
Nodes (19): fetch_tweet(), _block_old_session(), _html(), _patch_requests_get(), fake_get(), _Resp, test_fetch_tweet_accepts_twitter_and_mobile(), fake_get() (+11 more)

### Community 17 - "test_qc_fail_closed, test_translation"
Cohesion: 0.09
Nodes (14): translate_with_qc(), TranslationReview, test_admin_approval_still_required_when_ai_confident(), test_deterministic_issues_flag_ok_false(), test_qc_crash_is_fail_closed(), test_qc_normal_review_not_human(), test_qc_unavailable_review_object(), test_revision_body_only_keeps_title() (+6 more)

### Community 18 - "test_sources, romano"
Cohesion: 0.08
Nodes (12): main(), first_image_in_html(), parse_rss(), _canonical(), fetch(), test_concurrent_collect_respects_order(), test_rss_http_500(), test_rss_malformed() (+4 more)

### Community 19 - "lfc_official, base"
Cohesion: 0.14
Nodes (17): _scrape(), main(), main(), clean_text(), http_get(), meta(), soup_of(), _article_images() (+9 more)

### Community 20 - "translate, "
Cohesion: 0.13
Nodes (19): test_prompt_roles_and_no_fixed_manager_identity(), _apply_glossary(), _build_messages(), _build_prompt(), contains_error_signature(), _deep_translate(), _get_router(), _glossary_block() (+11 more)

### Community 21 - "fxembed, test_fxembed"
Cohesion: 0.10
Nodes (16): _api_get(), _base(), _best_mp4(), _cfg(), fetch_tweet(), _map_media(), _map_quote(), _own_statuses() (+8 more)

### Community 22 - "2026-08-31-hashtags-sources-videos, DESIGN_SYSTEM"
Cohesion: 0.09
Nodes (19): Translation quality benchmark, Claude Code memory and project context, Generated work dashboard placeholder, Telegram message design system, Persian admin review draft, Admin and channel message templates, Approved public channel message, Accepted helper script restructuring decision (+11 more)

### Community 23 - "test_queue_pipeline, db"
Cohesion: 0.18
Nodes (20): checkpoint_map(), count(), ingest_batch(), normalize_title(), queue_items(), save(), Durable news pipeline operation, SourceBatch (+12 more)

### Community 24 - "twitter"
Cohesion: 0.15
Nodes (16): _accounts(), clean_entries(), _due_accounts(), feed_url(), is_junk(), _load(), _mirror_health(), _mirror_is_backed_off() (+8 more)

### Community 25 - "test_e2e, "
Cohesion: 0.09
Nodes (12): fake_source_item(), test_admin_followup_message_is_not_whitespace_only(), test_e2e_failure_scenario(), fake_sources(), good(), verify(), fake_sources(), test_process_item_admin_link_translation_failure_still_drafts() (+4 more)

### Community 26 - "test_telegram"
Cohesion: 0.10
Nodes (12): test_approve_always_sends_to_group(), test_approve_manual_publishes_clean(), test_approve_records_feedback(), test_approve_send_failure(), test_handle_callback_approve(), test_handle_callback_send_to_channel(), test_process_item_send_failure_retry_pending(), test_process_item_success() (+4 more)

### Community 27 - "userbot_downloader, "
Cohesion: 0.13
Nodes (7): get_downloader(), parse_button_quality_and_size(), select_best_quality_button(), TwitterVidDownloader, edit_msg_handler(), new_msg_handler(), process_msg()

### Community 28 - "test_xscrape, "
Cohesion: 0.09
Nodes (8): extract_relay_script(), test_classic_mode_default_does_not_scrape(), test_dead_cycle_falls_back_to_classic(), test_extract_relay_script_found(), test_extract_relay_script_missing(), test_main_regex_matches_bare_link_only(), test_video_fallback_to_fx_when_scrape_has_none(), test_xscrape_mode_never_touches_nitter()

### Community 29 - "health"
Cohesion: 0.18
Nodes (15): alert(), _blank(), _bucket(), clear_alert(), cooldown_left(), _esc(), _fmt_dur(), is_available() (+7 more)

### Community 30 - "test_independent_translation, translate"
Cohesion: 0.13
Nodes (14): response(), test_google_fallback_does_not_truncate(), translate(), test_invalid_model_output_tries_next_provider(), completion(), test_long_article_resumes_only_failed_chunk(), test_semantic_revisions_are_bounded(), test_short_news_does_not_reserve_full_article_token_budget() (+6 more)

### Community 31 - "test_fxembed_cycles, check_accounts"
Cohesion: 0.13
Nodes (9): main(), test_account(), evaluate(), run(), run_model(), check(), new_ts(), run_cycle() (+1 more)

### Community 32 - "db, main"
Cohesion: 0.12
Nodes (12): channel_target(), get(), get_analysis(), get_verification(), record_feedback(), set_status(), approve(), _send_final_post() (+4 more)

### Community 33 - "test_source_detection, twitter"
Cohesion: 0.12
Nodes (10): detect_original_source(), detect_original_sources(), test_build_caption_combines_multiple_sources(), test_mention_at_end_after_emoji(), test_mention_middle_of_text(), test_no_mention_returns_none(), test_own_mention_ignored(), test_santi_handle_maps_to_name() (+2 more)

### Community 34 - "xscrape"
Cohesion: 0.14
Nodes (10): extract_author(), extract_card_image(), extract_media(), extract_note_tweet_text(), extract_quoted_tweet(), _fetch_html(), fetch_page(), _fetch_script() (+2 more)

### Community 35 - "db, main"
Cohesion: 0.12
Nodes (11): mark_attempt(), record_analysis(), set_admin_msg(), stage_failed(), update_payload(), _get_editor(), _has_translatable_text(), _process_item_internal() (+3 more)

### Community 36 - "test_extract_json, translate"
Cohesion: 0.13
Nodes (10): test_extract_json_braces_inside_metadata_do_not_confuse(), test_extract_json_codefence_still_works(), test_extract_json_ignores_trailing_html_comment(), test_extract_json_plain_still_works(), test_extract_json_salvages_malformed_qwen_output(), test_extract_json_unterminated_trailing_junk(), test_rejects_gibberish_qwen_salvage(), _balanced_json() (+2 more)

### Community 37 - "twitter, test_fxembed"
Cohesion: 0.16
Nodes (11): record_counter(), _entries_to_items(), fetch(), fetch_batch(), _fetch_classic(), _fetch_fxembed(), _fetch_fxembed_batch(), _fetch_xscrape() (+3 more)

### Community 38 - "db_prune, probe_fx_contract"
Cohesion: 0.14
Nodes (4): _conn(), _now(), prune(), vacuum()

### Community 39 - "lfc_mcp_server"
Cohesion: 0.20
Nodes (14): _get_db(), _json_dumps(), main(), _rpc(), _tool_channel_examples(), _tool_get_news(), _tool_get_news_by_id(), _tool_recent_published() (+6 more)

### Community 40 - "channel_guard, check_channel"
Cohesion: 0.21
Nodes (8): cfg(), _channel_web_url(), check(), norm(), refresh(), _score(), status(), main()

### Community 41 - "test_translate_output, translate"
Cohesion: 0.15
Nodes (11): _Choice, _FakeRouter, _Msg, _Resp, test_is_relevant_counts_club_hashtags(), test_strip_hashtags_cleans_x3c_artifact(), test_strip_hashtags_keeps_normal_text_untouched(), test_strip_hashtags_persian_hashtag() (+3 more)

### Community 42 - "schemas, test_ai"
Cohesion: 0.23
Nodes (7): _clean_str(), _in(), SchemaError, _to_float(), _to_int(), test_malformed_ai_response_falls_back(), analyze()

### Community 43 - "_template, index"
Cohesion: 0.18
Nodes (16): Analysis template, Decision template, EngineRule template, Idea template, Identity template, Research template, Session template, Concept template (+8 more)

### Community 44 - "source_health, db"
Cohesion: 0.18
Nodes (9): list_source_health(), source_health_status(), _fetch_source(), _backoff_seconds(), is_due(), mark_fail(), mark_ok(), record() (+1 more)

### Community 45 - "translate, benchmark"
Cohesion: 0.16
Nodes (9): main(), run_one(), score(), test_audio_models_are_not_translation_providers(), _chain(), chain_names(), _deployments(), _env_int() (+1 more)

### Community 46 - "probe_sources"
Cohesion: 0.27
Nodes (11): _accounts(), _fx_get(), _load(), main(), print_fx_summary(), print_x_summary(), probe_fx(), probe_x() (+3 more)

### Community 47 - "SKILL, ARTICLE_PIPELINE_PLAN"
Cohesion: 0.15
Nodes (9): Fetch, normalize, deduplicate, translate, review, publish, persist, Pending complete article translation and ordered Telegraph assembly, Admin edits preserve formatting and bypass automated text reshaping, Hermes reasons; Python owns infrastructure, Unavailable QC requires human review; revisions are bounded, Tweet and QC changes require restart and live verification, QC checks source fidelity, glossary, exact facts, and channel style, Translator preserves viewpoint, glossary names, numbers, and all content (+1 more)

### Community 48 - "conftest, "
Cohesion: 0.20
Nodes (8): fake_tg(), irrelevant_item(), isolated_pipeline_storage(), news_db(), official_item(), patched_main(), sample_item(), tmp_db()

### Community 49 - "conftest, test_e2e"
Cohesion: 0.14
Nodes (6): fake_hermes(), FakeHermesClient, __init__(), test_e2e_happy_path(), __init__(), verify()

### Community 51 - "twitter, base"
Cohesion: 0.15
Nodes (7): extract_tweet_id_from_link(), _attach_media(), _enrich_fxtwitter(), _enrich_tweet(), _enrich_vxtwitter(), resolve_video(), tweet_has_video()

### Community 52 - "test_translation, quality_control"
Cohesion: 0.24
Nodes (8): check_facts(), test_correct_translation_no_issues(), test_latin_leftover_detected(), test_missing_facts_detected(), test_title_number_only_in_body_is_fine(), test_title_wrong_name_detected(), test_wrong_name_detected(), test_wrong_number_detected()

### Community 53 - "test_fxembed, fxembed"
Cohesion: 0.18
Nodes (8): suspension_reason(), _patch(), test_204_means_nothing_new(), test_network_error_never_raises(), test_suspended_account_returns_empty(), test_suspension_reason_detects_not_found(), test_suspension_reason_detects_suspended(), test_suspension_reason_none_for_healthy_account()

### Community 54 - "twitter"
Cohesion: 0.15
Nodes (8): _extract_tweets(), _read_many_syndication(), syndication_fetch(), _sort_key(), tweet_age_hours(), _tweet_author(), _tweet_media(), _twitter_date_to_rfc822()

### Community 55 - "quality_control"
Cohesion: 0.18
Nodes (6): _apply_revision(), _missing_names(), _names(), _norm_digits(), _numbers(), style_examples()

### Community 56 - "DECISIONS, PROJECT_STATUS"
Cohesion: 0.20
Nodes (10): Bounded delivery retry state machine, Concurrent collection with source backoff and jitter, FxEmbed timestamp overlap and success-only cursor persistence, FxEmbed bounded pagination: default three pages, sixty posts, Suspended or deleted accounts cool down twenty-four hours, Bounded database retention trims heavy data and deletes old rows, Documented risk of Telegram failures silently stopping delivery, Perishable relevance keywords, quoted text, and bounded tweet checks (+2 more)

### Community 57 - "doctor, "
Cohesion: 0.35
Nodes (9): check_env(), head(), main(), mask(), port_open(), scan(), test_chain(), test_telegram() (+1 more)

### Community 59 - "test_state, "
Cohesion: 0.18
Nodes (3): test_channel_examples_only_approved(), test_rejected_news_has_error_reason(), analyze()

### Community 60 - "test_xscrape, xscrape"
Cohesion: 0.27
Nodes (8): parse_relay_tweets(), _relay_script(), test_best_bitrate_variant_wins(), test_parse_count_cap(), test_parse_relay_tweets_falls_back_to_full_text(), test_parse_shape_and_sort(), test_photo_urls_get_size_suffix(), test_pinned_entries_skipped()

### Community 62 - "test_twittervid_bot"
Cohesion: 0.22
Nodes (5): main(), poll_reply(), request_video(), _require_env(), start_client()

### Community 63 - "test_xscrape, xscrape"
Cohesion: 0.20
Nodes (5): _ms_to_rfc822(), scrape_user(), test_scrape_user_entry_parity(), test_scrape_user_network_error(), test_scrape_user_no_relay_data()

### Community 64 - "sample_item, test_send"
Cohesion: 0.31
Nodes (4): all_samples(), get(), main(), result()

### Community 65 - "test_fxembed"
Cohesion: 0.22
Nodes (5): _statuses(), test_no_pagination_without_since(), test_pagination_deduplicates_overlap(), test_pagination_follows_cursor_when_since_used(), test_pagination_respects_max_pages()

### Community 66 - "test_xscrape"
Cohesion: 0.22
Nodes (5): _b64(), _note_script(), test_parse_relay_tweets_prefers_note_tweet(), test_quoted_tweet_prefers_note_tweet_text(), test_quoted_tweet_sets_original_source()

### Community 67 - "test_xscrape"
Cohesion: 0.28
Nodes (5): _fresh_entry(), _patch_twitter_fetch(), test_fetch_xscrape_checks_all_tweets_not_just_three(), test_fetch_xscrape_quoted_text_counts_for_relevance(), test_fetch_xscrape_squad_player_name_counts_for_relevance()

### Community 68 - "twitter, base"
Cohesion: 0.25
Nodes (4): images_in_html(), fix_image(), _own_media_urls(), tweet_image()

### Community 69 - "test_multi_video"
Cohesion: 0.29
Nodes (3): _entry_with_media(), test_attach_media_sets_all_video_urls(), test_send_media_group_supports_video_album_with_caption()

### Community 70 - "translate"
Cohesion: 0.25
Nodes (4): _parse_junk_array(), _parse_junk_scalar(), _parse_junk_string(), _salvage_json_object()

### Community 71 - "twitter"
Cohesion: 0.29
Nodes (4): build_tweet_item(), canonical(), _dedupe_parts(), tweet_text()

### Community 72 - "2026-08-23-xscrape-feature, 2026-08-25-tweet-link-session"
Cohesion: 0.40
Nodes (4): August 23 restructuring and xscrape session, Accepted direct X scraping decision, Proposed admin tweet link processing plan, Implemented admin tweet link session

### Community 73 - "bluesky"
Cohesion: 0.47
Nodes (3): fetch(), _fetch_author(), _post_images()

### Community 74 - "HERMES_INTEGRATION, SKILL"
Cohesion: 0.40
Nodes (3): Hermes mistakes source wording confirmed for official confirmation, Editor classification with conservative review and anti-hallucination, Verifier requires independent evidence and never uses memory

### Community 77 - ".mcp"
Cohesion: 0.50
Nodes (3): OKF_ROOT, npx, samemind

## Ambiguous Edges - Review These
- `Manual forwarding publication workflow` → `Approved public channel message`  [AMBIGUOUS]
  QUICKSTART.md · relation: conceptually_related_to

## Knowledge Gaps
- **29 isolated node(s):** `npx`, `OKF_ROOT`, `redeploy.sh script`, `watchdog.sh script`, `_Msg` (+24 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 653 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Manual forwarding publication workflow` and `Approved public channel message`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `HermesClient` connect `hermes_client, test_verification` to `schemas, test_ai`, `hermes_client, test_verification`, `test_ai, test_decision`?**
  _High betweenness centrality (0.003) - this node is a cross-community bridge._
- **Why does `NewsEditor` connect `test_image, image_selector` to `editor, test_decision`, `hermes_client, test_verification`, `test_ai, test_decision`?**
  _High betweenness centrality (0.002) - this node is a cross-community bridge._
- **Why does `translate()` connect `test_independent_translation, translate` to `translate, `?**
  _High betweenness centrality (0.002) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `NewsEditor` (e.g. with `HermesClient` and `NewsAnalysis`) actually correct?**
  _`NewsEditor` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `npx`, `OKF_ROOT`, `redeploy.sh script` to the rest of the system?**
  _29 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `telegram_api, names` be split into smaller, more focused modules?**
  _Cohesion score 0.05030181086519115 - nodes in this community are weakly interconnected._
