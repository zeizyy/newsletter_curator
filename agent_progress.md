# Agent Progress

This file is append-only. Each coding session should add a short dated entry with:
- task worked on
- files changed
- tests run
- outcome
- open risks
- next recommended task

## Session Contract

1. Run `pwd`.
2. Read `agent_progress.md`.
3. Read `agent_tasks.json`.
4. Run `./init.sh`.
5. Choose exactly one pending task whose dependencies are complete.
6. Implement only that task plus minimal prerequisite refactors.
7. Add or update the task's integration test.
8. Run the task's test command and any needed regression tests.
9. Commit the completed task to the git repository `https://github.com/zeizyy/newsletter_curator` with a descriptive non-interactive commit message.
10. Update task status in `agent_tasks.json`.
11. Append a new entry here before ending the session.

## Initial Entry

### 2026-03-21 - Harness initialized
- Context: Created the task harness files for the central-fetch migration plan.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `init.sh`
- Tests run: artifact validation only
- Outcome: Follow-on coding agents now have a dependency-ordered task list and session contract.
- Open risks: The repo does not yet have `pytest` or integration test scaffolding; that is intentionally deferred to `T0`.
- Next recommended task: `T0` Initialize the long-running agent harness.

## Session Log

Add new entries below this line.

### 2026-04-05 - T72 resolved README, checked-in config, and UI artifact consistency drift
- Context: Audited the checked-in docs, defaults, preview surfaces, subscriber settings copy, and PDF naming after the recent subscriber and public-host work, then tightened the repo so those surfaces describe the same product behavior again.
- Files changed: `README.md`, `config.yaml`, `curator/config.py`, `admin_app.py`, `main.py`, `curator/jobs.py`, `curator/pdf.py`, `templates/admin_config.html`, `templates/digest_preview.html`, `templates/subscriber_account.html`, `templates/subscriber_login.html`, `templates/subscriber_settings.html`, `tests/integration/test_config_and_preview_consistency.py`, `tests/integration/test_admin_config_page_uses_shared_shell.py`, `tests/integration/test_admin_preview_renders_digest.py`, `tests/integration/test_subscriber_settings_page_persists_profile.py`, `tests/integration/test_subscriber_pdf_delivery_opt_in.py`, `agent_spec.md`, `agent_tasks.json`, `agent_contracts/T72_consistency_pass.md`
- Tests run: `uv run pytest tests/integration/test_config_and_preview_consistency.py tests/integration/test_admin_config_page_uses_shared_shell.py tests/integration/test_admin_preview_renders_digest.py tests/integration/test_subscriber_settings_page_persists_profile.py tests/integration/test_subscriber_pdf_delivery_opt_in.py -q`; `uv run pytest tests/integration/test_delivery_public_host_links_and_fallback.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_default_config_includes_repo_persona.py -q`; `python3 -m json.tool agent_tasks.json >/dev/null`; `git diff --check`
- Outcome: The checked-in config now keeps telemetry off by default and explicitly carries the newer database or tracking knobs, the README matches the current personalization and tracking behavior, admin and subscriber copy now describe persona and preferred sources as final-ranking-only signals, email-safe preview reuses the delivered settings-link logic, preview capture preserves attachment metadata, and the PDF artifact now uses digest-facing naming.
- Open risks: Preview still shows only the default audience variant, so personalized-profile preview remains out of scope for this pass.
- Next recommended task: `T43` Persist explicit servability status, blocked reasons, detector version, and classifier signals.

### 2026-04-05 - T72 follow-up fixed remaining config parity
- Context: A post-implementation evaluator pass caught one remaining drift point after the first commit: `additional_sources.max_total` and tracking toggle defaults still disagreed between runtime defaults and the checked-in config.
- Files changed: `config.yaml`, `curator/config.py`, `README.md`, `tests/integration/test_config_and_preview_consistency.py`
- Tests run: `uv run pytest tests/integration/test_config_and_preview_consistency.py tests/integration/test_discovery_fetch_budget_increases_recall.py tests/integration/test_default_config_includes_repo_persona.py -q`
- Outcome: The checked-in config now uses `additional_sources.max_total = 30`, runtime defaults explicitly include `tracking.open_enabled` and `tracking.click_enabled`, and the config-parity regression now checks the actual intended alignment instead of asserting the mismatch.
- Open risks: Preview still shows only the default audience variant, so personalized-profile preview remains out of scope for this pass.
- Next recommended task: `T43` Persist explicit servability status, blocked reasons, detector version, and classifier signals.

### 2026-03-21 - T0 initialized offline test scaffolding
- Context: Built the first executable engineering task in the harness and kept the current pipeline behavior unchanged.
- Files changed: `pyproject.toml`, `uv.lock`, `tests/__init__.py`, `tests/conftest.py`, `tests/fakes.py`, `tests/helpers.py`, `tests/fixtures/newsletter_sample.html`, `tests/integration/test_smoke_offline_pipeline.py`, `agent_tasks.json`
- Tests run: `uv run pytest tests/integration/test_smoke_offline_pipeline.py`
- Outcome: Added offline-first pytest scaffolding, deterministic fake Gmail/source/article/OpenAI adapters, temp config and temp DB helpers, and a passing smoke integration test that drives the existing delivery pipeline without network access.
- Open risks: The current test run still emits third-party deprecation warnings from `httplib2`.
- Next recommended task: `T1` Refactor the monolith into modules behind interfaces with no behavior change.

### 2026-03-21 - T1 split runtime into modules behind interfaces
- Context: Refactored the single-file runtime into a `curator/` package while keeping `main.py` as the compatibility and composition layer.
- Files changed: `main.py`, `curator/__init__.py`, `curator/config.py`, `curator/gmail.py`, `curator/content.py`, `curator/llm.py`, `curator/sources.py`, `curator/rendering.py`, `curator/pipeline.py`, `tests/integration/test_legacy_equivalent_delivery.py`, `agent_tasks.json`
- Tests run: `uv run pytest tests/integration/test_smoke_offline_pipeline.py tests/integration/test_legacy_equivalent_delivery.py`; `uv run python -c "import admin_app, main; print('ok')"`
- Outcome: The runtime responsibilities are now separated by concern, `main.py` remains monkeypatch-friendly for the existing harness, and the entrypoint behavior is preserved by a passing legacy-equivalent integration test.
- Open risks: The package boundaries are cleaner, but deeper abstractions such as a repository layer do not exist yet; that starts in `T2`. Third-party `httplib2` deprecation warnings still appear during tests.
- Next recommended task: `T2` Add persistence and migrations for the central content repository.

### 2026-03-21 - T2 added SQLite repository and migration bootstrap
- Context: Added the persistence layer needed for the upcoming centralized fetch and delivery split without changing the live newsletter flow yet.
- Files changed: `curator/config.py`, `curator/repository.py`, `tests/integration/test_repository_upsert_and_dedupe.py`, `agent_tasks.json`
- Tests run: `uv run pytest tests/integration/test_smoke_offline_pipeline.py tests/integration/test_legacy_equivalent_delivery.py tests/integration/test_repository_upsert_and_dedupe.py`
- Outcome: The repo now has a SQLite-backed content repository with migration bootstrap, run tracking, idempotent source and story upserts, article snapshots, source selection storage, and repository query helpers covered by an integration test.
- Open risks: The repository exists, but the fetch and delivery jobs do not use it yet; that starts in `T3` and `T4`. Third-party `httplib2` deprecation warnings still appear during tests.
- Next recommended task: `T3` Build the centralized source-fetch job.

### 2026-03-21 - T3 built centralized source fetch job
- Context: Added the first standalone cron-friendly job that populates the repository from centrally fetched sources without running newsletter delivery.
- Files changed: `curator/jobs.py`, `fetch_sources.py`, `tests/integration/test_fetch_sources_job_writes_repository.py`, `agent_tasks.json`
- Tests run: `uv run pytest tests/integration/test_smoke_offline_pipeline.py tests/integration/test_legacy_equivalent_delivery.py tests/integration/test_repository_upsert_and_dedupe.py tests/integration/test_fetch_sources_job_writes_repository.py`
- Outcome: The repo now has a dedicated fetch job, a `fetch_sources.py` entrypoint, ingestion-run recording, story upserts, article snapshot persistence, and an integration test that verifies repeated runs remain idempotent.
- Open risks: Delivery still reads direct sources live instead of the repository; `T4` will move that read path. Third-party `httplib2` deprecation warnings still appear during tests.
- Next recommended task: `T4` Switch newsletter delivery to use the central repository for non-Gmail sources.

### 2026-03-21 - T4 switched delivery to repository-backed source reads
- Context: Moved the non-Gmail delivery path off live direct-source fetches and onto the centralized repository created by the new fetch job.
- Files changed: `main.py`, `curator/sources.py`, `curator/pipeline.py`, `tests/integration/test_delivery_uses_repository_not_live_fetch.py`, `agent_tasks.json`
- Tests run: `uv run pytest tests/integration/test_smoke_offline_pipeline.py tests/integration/test_legacy_equivalent_delivery.py tests/integration/test_repository_upsert_and_dedupe.py tests/integration/test_fetch_sources_job_writes_repository.py tests/integration/test_delivery_uses_repository_not_live_fetch.py`
- Outcome: Delivery now loads centrally fetched source stories from SQLite, uses stored `article_text` when available, and succeeds with live source/article fetches disabled for repository-backed stories.
- Open risks: Source selection is not yet user-configurable in the admin UI; `T5` will add that layer. Third-party `httplib2` deprecation warnings still appear during tests.
- Next recommended task: `T5` Add repository-backed source selection in the admin app.

### 2026-03-21 - T5 added admin-backed source selection
- Context: Extended the existing config UI so centrally fetched sources can be enabled or disabled in SQLite and the delivery path respects those selections.
- Files changed: `admin_app.py`, `templates/admin_config.html`, `curator/repository.py`, `curator/sources.py`, `tests/integration/test_admin_source_selection_filters_delivery.py`, `agent_tasks.json`
- Tests run: `uv run pytest tests/integration/test_smoke_offline_pipeline.py tests/integration/test_legacy_equivalent_delivery.py tests/integration/test_repository_upsert_and_dedupe.py tests/integration/test_fetch_sources_job_writes_repository.py tests/integration/test_delivery_uses_repository_not_live_fetch.py tests/integration/test_admin_source_selection_filters_delivery.py`
- Outcome: The admin app now renders repository-discovered sources with enable/disable toggles, persists those settings in SQLite, and delivery excludes disabled centrally fetched sources.
- Open risks: Development still requires either live fetches or test monkeypatching; `T6` will introduce an explicit canned-data development mode. Third-party `httplib2` warnings remain, and `admin_app.py` still uses `datetime.utcnow()` for config backup filenames.
- Next recommended task: `T6` Add canned central-fetch mode for development.

### 2026-03-21 - T6 added canned offline development mode
- Context: Added a config-driven offline development path so local iteration can use canned centrally fetched stories and deterministic inference instead of live domains and OpenAI calls.
- Files changed: `curator/config.py`, `curator/dev.py`, `curator/jobs.py`, `curator/sources.py`, `main.py`, `tests/fixtures/canned_sources.json`, `tests/integration/test_offline_canned_repository_mode.py`, `agent_tasks.json`
- Tests run: `uv run pytest tests/integration/test_smoke_offline_pipeline.py tests/integration/test_legacy_equivalent_delivery.py tests/integration/test_repository_upsert_and_dedupe.py tests/integration/test_fetch_sources_job_writes_repository.py tests/integration/test_delivery_uses_repository_not_live_fetch.py tests/integration/test_admin_source_selection_filters_delivery.py tests/integration/test_offline_canned_repository_mode.py`
- Outcome: The repo now supports canned source ingestion, deterministic fake ranking and summarization, and an offline end-to-end development workflow that uses repository snapshots instead of live fetches.
- Open risks: Persona-aware prompt handling is still pending in `T7`, and Gmail is still live-read during delivery until the now-required `T8` ingest milestone lands. `admin_app.py` still emits a `datetime.utcnow()` deprecation warning during tests.
- Next recommended task: `T7` Add persona-aware ranking and summarization. `T8` is now a required milestone and a dependency for `T9`.

### 2026-03-21 - T7 added persona-aware ranking and summaries
- Context: Added persona configuration and centralized prompt builders so ranking and “why this matters” can be tailored to a user persona without changing the surrounding pipeline shape.
- Files changed: `curator/config.py`, `curator/prompts.py`, `curator/llm.py`, `curator/dev.py`, `main.py`, `admin_app.py`, `templates/admin_config.html`, `tests/helpers.py`, `tests/integration/test_persona_changes_ranking_and_summary.py`, `agent_tasks.json`
- Tests run: `uv run pytest tests/integration/test_smoke_offline_pipeline.py tests/integration/test_legacy_equivalent_delivery.py tests/integration/test_repository_upsert_and_dedupe.py tests/integration/test_fetch_sources_job_writes_repository.py tests/integration/test_delivery_uses_repository_not_live_fetch.py tests/integration/test_admin_source_selection_filters_delivery.py tests/integration/test_offline_canned_repository_mode.py tests/integration/test_persona_changes_ranking_and_summary.py`
- Outcome: Persona text is now configurable, prompt construction is centralized, both live and deterministic development inference paths can use persona context, and the integration test verifies that two personas produce different story selection and summary language.
- Open risks: Gmail is still live-read during delivery until `T8` lands. `admin_app.py` still emits a `datetime.utcnow()` deprecation warning during tests.
- Next recommended task: `T8` Ingest Gmail into the same repository for full delivery decoupling.

### 2026-03-21 - T8 ingested Gmail into the repository and enabled repo-first delivery
- Context: Added a standalone Gmail ingest job and switched delivery to prefer repository-stored Gmail candidates so the newsletter can run without live Gmail reads after ingest has populated the DB.
- Files changed: `curator/gmail.py`, `curator/jobs.py`, `curator/pipeline.py`, `main.py`, `fetch_gmail.py`, `tests/integration/test_gmail_ingest_then_delivery_from_db.py`, `agent_tasks.json`
- Tests run: `uv run pytest tests/integration/test_smoke_offline_pipeline.py tests/integration/test_legacy_equivalent_delivery.py tests/integration/test_repository_upsert_and_dedupe.py tests/integration/test_fetch_sources_job_writes_repository.py tests/integration/test_delivery_uses_repository_not_live_fetch.py tests/integration/test_admin_source_selection_filters_delivery.py tests/integration/test_offline_canned_repository_mode.py tests/integration/test_persona_changes_ranking_and_summary.py tests/integration/test_gmail_ingest_then_delivery_from_db.py`
- Outcome: The repo now has `fetch_gmail.py`, Gmail candidate and article snapshot persistence, and a repo-first Gmail delivery path verified by an integration test that fails if delivery attempts live Gmail reads.
- Open risks: The compatibility fallback to live Gmail reads still exists and should be removed during `T9`. `admin_app.py` still emits a `datetime.utcnow()` deprecation warning during tests.
- Next recommended task: `T9` Finalize the two-job production flow and remove obsolete paths.

### 2026-03-21 - T9 finalized the repository-first production flow
- Context: Removed the remaining delivery-time live-read assumptions, added the dedicated delivery entrypoint, recorded delivery readiness in the repository, and documented the final cron-friendly job split.
- Files changed: `.gitignore`, `README.md`, `admin_app.py`, `config.yaml`, `curator/gmail.py`, `curator/jobs.py`, `curator/pipeline.py`, `curator/repository.py`, `deliver_digest.py`, `main.py`, `tests/helpers.py`, `tests/integration/test_admin_source_selection_filters_delivery.py`, `tests/integration/test_delivery_uses_repository_not_live_fetch.py`, `tests/integration/test_full_two_job_pipeline.py`, `tests/integration/test_legacy_equivalent_delivery.py`, `tests/integration/test_persona_changes_ranking_and_summary.py`, `tests/integration/test_smoke_offline_pipeline.py`, `agent_tasks.json`
- Tests run: `uv run pytest tests/integration`
- Outcome: Delivery is now repository-only by default, `deliver_digest.py` mirrors the final production architecture, delivery runs are recorded with readiness metadata, stale or failed latest ingests are surfaced without blocking healthy source types, and the new two-job end-to-end integration test passes.
- Open risks: Third-party `httplib2` deprecation warnings still appear during test startup, but the app code no longer emits the previous `datetime.utcnow()` warning.
- Next recommended task: none; all tasks in `agent_tasks.json` are complete.

### 2026-03-21 - T10 added on-demand web preview for the newsletter
- Context: Extended the admin app so the current repository-backed digest can be rendered on demand in the browser without sending email.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `main.py`, `templates/admin_config.html`, `templates/digest_preview.html`, `tests/integration/test_admin_preview_renders_digest.py`
- Tests run: `uv run pytest tests/integration/test_admin_preview_renders_digest.py tests/integration/test_admin_source_selection_filters_delivery.py tests/integration/test_delivery_uses_repository_not_live_fetch.py`
- Outcome: The admin UI now exposes a preview page that runs the real repository-backed digest pipeline, captures the rendered HTML and plain-text output, and shows the newsletter in a web page on demand.
- Open risks: The admin UI still only exposes configuration and preview flows; browsing all fetched repository stories is the next missing operator surface.
- Next recommended task: `T11` Add an admin story explorer for centrally fetched stories.

### 2026-03-21 - T11 added an admin story explorer for repository stories
- Context: Added a simple operator view for browsing centrally fetched stories so repository contents can be inspected directly from the admin app.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `templates/admin_config.html`, `templates/digest_preview.html`, `templates/story_explorer.html`, `tests/integration/test_admin_story_explorer_lists_repository_stories.py`
- Tests run: `uv run pytest tests/integration/test_admin_story_explorer_lists_repository_stories.py tests/integration/test_admin_preview_renders_digest.py`
- Outcome: The admin UI now exposes a `/stories` view with recent-first repository stories, source/category/publish metadata, snapshot status, and simple source filters.
- Open risks: Repository growth is still unbounded until TTL cleanup lands in `T12`.
- Next recommended task: `T12` Add a seven-day TTL cleanup for centrally fetched stories.

### 2026-03-21 - T12 added seven-day TTL cleanup for centrally fetched stories
- Context: Added automatic retention cleanup to the ingest flow so repository growth is bounded without requiring a separate manual maintenance step.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `config.yaml`, `curator/config.py`, `curator/jobs.py`, `curator/repository.py`, `tests/integration/test_repository_ttl_cleanup_removes_old_stories.py`
- Tests run: `uv run pytest tests/integration/test_repository_ttl_cleanup_removes_old_stories.py tests/integration/test_fetch_sources_job_writes_repository.py tests/integration/test_gmail_ingest_then_delivery_from_db.py`
- Outcome: Both scheduled ingest jobs now run a seven-day TTL cleanup for centrally fetched stories, old article snapshots are removed via cascade, and cleanup stats are recorded in ingest results.
- Open risks: Paywalled stories can still enter the repository and surface in digests until `T13` lands.
- Next recommended task: `T13` Add token-efficient paywall detection and exclude paywalled stories from the newsletter.

### 2026-03-21 - T13 added token-efficient paywall detection and digest filtering
- Context: Added deterministic paywall heuristics in the ingest path and filtered flagged stories out of repository-backed preview and delivery reads.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/content.py`, `curator/gmail.py`, `curator/jobs.py`, `curator/repository.py`, `curator/sources.py`, `templates/story_explorer.html`, `tests/integration/test_paywalled_stories_are_excluded_from_digest.py`
- Tests run: `uv run pytest tests/integration/test_paywalled_stories_are_excluded_from_digest.py tests/integration/test_admin_preview_renders_digest.py tests/integration/test_fetch_sources_job_writes_repository.py tests/integration/test_gmail_ingest_then_delivery_from_db.py`
- Outcome: Ingest now marks likely paywalled snapshots without LLM calls, paywall state is persisted in the repository, and paywalled stories are excluded from preview and delivery while remaining visible to operators in the story explorer.
- Open risks: Third-party `httplib2` deprecation warnings still appear during test startup, but the requested feature wave is otherwise complete.
- Next recommended task: none; all tasks in `agent_tasks.json` are complete.

### 2026-03-22 - T14 moved per-article summarization into centralized fetch
- Context: Shifted summary generation from preview/delivery into the centralized Gmail and source ingest jobs so repository snapshots carry persona-aware summary content.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/gmail.py`, `curator/jobs.py`, `curator/pipeline.py`, `curator/repository.py`, `curator/sources.py`, `tests/integration/test_preview_uses_ingest_summaries_without_summary_llm.py`, `tests/integration/test_fetch_sources_job_writes_repository.py`, `tests/integration/test_full_two_job_pipeline.py`, `tests/integration/test_gmail_ingest_then_delivery_from_db.py`, `tests/integration/test_legacy_equivalent_delivery.py`, `tests/integration/test_paywalled_stories_are_excluded_from_digest.py`, `tests/integration/test_repository_upsert_and_dedupe.py`, `tests/integration/test_smoke_offline_pipeline.py`
- Tests run: `uv run pytest tests/integration/test_preview_uses_ingest_summaries_without_summary_llm.py`; `uv run pytest tests/integration -q`
- Outcome: Central fetch now stores summary snapshots and summary metadata in SQLite, preview/delivery reuse stored summaries instead of calling the summary model when available, and the integration suite passes after updating offline fetch-path expectations.
- Open risks: Summarization during ingest is still sequential; `T15` will add bounded concurrency to reduce fetch latency. Third-party `httplib2` deprecation warnings still appear during test startup.
- Next recommended task: `T15` Parallelize centralized summarization during fetch.

### 2026-03-22 - T15 parallelized centralized summarization during fetch
- Context: Split the ingest path into preparation, bounded concurrent summarization, and serial persistence so summary-model calls can overlap without making SQLite writes concurrent.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/jobs.py`, `tests/integration/test_fetch_summarization_runs_concurrently.py`
- Tests run: `uv run pytest tests/integration/test_fetch_summarization_runs_concurrently.py tests/integration/test_preview_uses_ingest_summaries_without_summary_llm.py tests/integration/test_fetch_sources_job_writes_repository.py tests/integration/test_gmail_ingest_then_delivery_from_db.py -q`; `uv run pytest tests/integration -q`
- Outcome: Fetch jobs now honor `limits.max_summary_workers`, summary generation runs concurrently up to the configured cap, repository writes remain ordered, and the new integration test proves the summary stage overlaps work.
- Open risks: Title and document metadata extraction still rely on custom parsing in places; `T16` will switch the ingest path to a Trafilatura-backed extractor. Third-party `httplib2` deprecation warnings still appear during test startup.
- Next recommended task: `T16` Adopt a battle-tested URL extraction library for robust title and article metadata parsing.

### 2026-03-22 - T16 adopted Trafilatura for ingest-time document metadata extraction
- Context: Replaced the brittle default article fetch parser with a Trafilatura-backed extractor so ingest can capture document titles and body text, then use those titles to overwrite generic CTA anchors like `Read More`.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/content.py`, `curator/jobs.py`, `pyproject.toml`, `uv.lock`, `tests/integration/test_fetch_sources_job_writes_repository.py`, `tests/integration/test_title_extraction_avoids_generic_read_more_titles.py`
- Tests run: `uv run pytest tests/integration/test_title_extraction_avoids_generic_read_more_titles.py tests/integration/test_fetch_summarization_runs_concurrently.py tests/integration/test_preview_uses_ingest_summaries_without_summary_llm.py tests/integration/test_admin_story_explorer_lists_repository_stories.py -q`; `uv run pytest tests/integration -q`
- Outcome: Default ingest now extracts article body and metadata via Trafilatura, generic newsletter CTA anchors are replaced with document titles when better metadata is available, and the story explorer regression test verifies the bad `Read More` titles are gone.
- Open risks: The repository still carries a growing migration chain; `T17` will collapse schema bootstrap into a single rebuilt baseline. Third-party `httplib2` deprecation warnings still appear during test startup.
- Next recommended task: `T17` Collapse repository migrations into a rebuilt baseline schema.

### 2026-03-22 - T17 collapsed repository bootstrap into a rebuilt baseline schema
- Context: Removed the incremental SQLite migration chain and replaced it with a current-schema bootstrap that recreates managed tables when it encounters an old migrated database.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/repository.py`, `tests/integration/test_repository_schema_bootstrap_after_reset.py`, `tests/integration/test_repository_upsert_and_dedupe.py`
- Tests run: `uv run pytest tests/integration/test_repository_schema_bootstrap_after_reset.py tests/integration/test_repository_upsert_and_dedupe.py tests/integration/test_fetch_sources_job_writes_repository.py tests/integration/test_gmail_ingest_then_delivery_from_db.py -q`; `uv run pytest tests/integration -q`
- Outcome: Repository initialization now creates the full current schema in one pass, old migrated DB files trigger a one-time managed-table reset instead of stepwise migration, and the new integration test verifies the reset path and current columns.
- Open risks: Third-party `httplib2` deprecation warnings still appear during test startup, but this feature wave is otherwise complete.
- Next recommended task: none; `T14` through `T17` are complete.

### 2026-03-21 - T18 removed the temporary 48-hour testing config path
- Context: Cleaned up the ad hoc `config.48h.yaml` artifact from manual testing and added a regression to keep the project on the default 24-hour Gmail/source windows for faster local runs.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `tests/integration/test_default_config_uses_24h_window.py`
- Tests run: `uv run pytest tests/integration/test_default_config_uses_24h_window.py -q`
- Outcome: The temporary 48-hour config file is gone, the default config remains `newer_than:1d` plus `additional_sources.hours = 24`, and the regression test locks that behavior in place.
- Open risks: The fetch path still summarizes every ingested article; `T19` will add a lightweight LLM scoring gate so only the top 20 articles are summarized each run.
- Next recommended task: `T19` Add a lightweight LLM scoring gate so only the top 20 articles are summarized per run.

### 2026-03-21 - T19 added a lightweight scoring gate before expensive summaries
- Context: Inserted a cheap batch LLM triage step into ingest so fetched article candidates are scored first and only the top 20 non-paywalled stories are sent to the expensive summary model.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/config.py`, `curator/prompts.py`, `curator/llm.py`, `curator/dev.py`, `curator/jobs.py`, `tests/integration/test_fetch_summarization_runs_concurrently.py`, `tests/integration/test_ingest_only_summarizes_top_twenty_scored_articles.py`
- Tests run: `uv run pytest tests/integration/test_ingest_only_summarizes_top_twenty_scored_articles.py tests/integration/test_fetch_summarization_runs_concurrently.py tests/integration/test_preview_uses_ingest_summaries_without_summary_llm.py tests/integration/test_fetch_sources_job_writes_repository.py -q`; `uv run pytest tests/integration -q`
- Outcome: Ingest now uses the lightweight reasoning model to rank fetched article candidates, persists score-selection metadata on snapshots, summarizes at most 20 stories per run, and keeps on-demand preview fallback behavior for unsummarized stories.
- Open risks: Third-party `httplib2` deprecation warnings still appear during test startup, but this requested task set is otherwise complete.
- Next recommended task: none; `T18` and `T19` are complete.

### 2026-03-21 - T20 restricted repository writes to servable summarized articles only
- Context: Tightened the T19 ingest contract so lower-ranked or paywalled candidates never land in SQLite; only stories that were selected for summarization and successfully summarized are persisted.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/jobs.py`, `tests/integration/test_ingest_only_summarizes_top_twenty_scored_articles.py`, `tests/integration/test_ingest_only_persists_top_twenty_summarized_articles.py`, `tests/integration/test_paywalled_stories_are_excluded_from_digest.py`
- Tests run: `uv run pytest tests/integration/test_ingest_only_summarizes_top_twenty_scored_articles.py tests/integration/test_ingest_only_persists_top_twenty_summarized_articles.py tests/integration/test_fetch_summarization_runs_concurrently.py tests/integration/test_fetch_sources_job_writes_repository.py -q`; `uv run pytest tests/integration -q`
- Outcome: Ingest now writes only servable summarized winners into the repository, repository counts reflect top-20-only persistence, and paywalled/unsummarized candidates remain completely absent from storage.
- Open risks: Third-party `httplib2` deprecation warnings still appear during test startup, but the requested repository-storage contract is now enforced.
- Next recommended task: none; `T20` is complete.

### 2026-03-21 - T21 switched legacy low-cost OpenAI defaults to GPT-5 mini
- Context: Replaced the remaining `gpt-4o-mini` default with `gpt-5-mini`, added a config-load upgrade path so older configs still switch automatically, and documented the before/after input-output pricing in the README.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/config.py`, `README.md`, `tests/integration/test_default_openai_models_use_gpt5_mini.py`
- Tests run: `uv run pytest tests/integration/test_default_openai_models_use_gpt5_mini.py tests/integration/test_default_config_uses_24h_window.py tests/integration/test_fetch_sources_job_writes_repository.py -q`
- Outcome: New configs now default both reasoning and summary to `gpt-5-mini`, legacy configs that still pin `gpt-4o-mini` for reasoning are upgraded automatically at load time, and the repo now records the exact per-1M token price delta for the switch.
- Open risks: The pricing table is a dated snapshot and should be re-verified against OpenAI pricing before future model changes. Third-party `httplib2` deprecation warnings still appear during test startup.
- Next recommended task: none; `T21` is complete.

### 2026-03-21 - T22 persisted the daily newsletter and reused it in preview and delivery
- Context: Added a repository-backed daily newsletter artifact keyed by day, then switched preview and delivery to read through that stored version when it already exists instead of regenerating the digest each time.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/repository.py`, `curator/pipeline.py`, `curator/jobs.py`, `tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py`, `tests/integration/test_ingest_only_summarizes_top_twenty_scored_articles.py`
- Tests run: `uv run pytest tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_admin_preview_renders_digest.py tests/integration/test_delivery_uses_repository_not_live_fetch.py tests/integration/test_full_two_job_pipeline.py -q`; `uv run pytest tests/integration -q`
- Outcome: A completed digest is now persisted in SQLite with the rendered text/html and selected story metadata, `/preview` reuses the stored digest for the current day, and the email delivery path sends the stored digest when it already exists for that day.
- Open risks: The daily digest key currently uses the UTC date with no configurable timezone override. Third-party `httplib2` deprecation warnings still appear during test startup.
- Next recommended task: `T23` Improve the newsletter UX across preview and delivered output.

### 2026-03-21 - T23 upgraded the shared newsletter UX
- Context: Improved the shared digest presentation rather than only the preview wrapper, so both the emailed newsletter and the preview frame now have stronger hierarchy, cleaner metadata treatment, and more readable summary sections.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/rendering.py`, `curator/pipeline.py`, `templates/digest.html`, `templates/digest_preview.html`, `tests/integration/test_newsletter_rendering_ux_improvements.py`
- Tests run: `uv run pytest tests/integration/test_newsletter_rendering_ux_improvements.py tests/integration/test_admin_preview_renders_digest.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py -q`; `uv run pytest tests/integration -q`
- Outcome: The digest now surfaces source and date metadata on each card, highlights the why-this-matters section more clearly, adds a stronger hero and section hierarchy, and gives the preview page clearer status and story-count visibility while reusing the same improved HTML.
- Open risks: The visual treatment now relies on additional CSS inside the email template, so very old email clients may collapse some of the richer spacing or pill styles. Third-party `httplib2` deprecation warnings still appear during test startup.
- Next recommended task: `T24` Add one-shot deployment instructions and server bootstrap script.

### 2026-03-21 - T24 added one-shot deployment bootstrap assets
- Context: Replaced the old manual cron-only deployment notes with a generated bootstrap that can produce and optionally install the admin server service, env file, runner scripts, and daily cron jobs in one pass.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `.gitignore`, `README.md`, `scripts/bootstrap_server.py`, `tests/integration/test_deployment_bootstrap_assets.py`
- Tests run: `uv run pytest tests/integration/test_deployment_bootstrap_assets.py -q`; `uv run python scripts/bootstrap_server.py --help`; `uv run pytest tests/integration -q`
- Outcome: The repo now includes a one-shot server bootstrap script, generated deployment assets for the admin server plus fetch and delivery jobs, and updated hosted-server instructions that match the script’s install and verification flow.
- Open risks: The one-shot install path currently targets `systemd --user` plus user crontab; non-systemd hosts or operators who need system-wide services will still need a small adaptation. Third-party `httplib2` deprecation warnings still appear during test startup.
- Next recommended task: none; `T24` is complete.

### 2026-03-21 - T25 switched deployment cron defaults to Pacific-time afternoons
- Context: Added explicit cron timezone support to the deployment bootstrap so hosted servers can stay on UTC while the generated daily jobs still run on Pacific time, then shifted the default schedules to late afternoon Pacific.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `README.md`, `scripts/bootstrap_server.py`, `tests/integration/test_deployment_bootstrap_assets.py`
- Tests run: `uv run pytest tests/integration/test_deployment_bootstrap_assets.py -q`
- Outcome: Generated cron assets now include `CRON_TZ=America/Los_Angeles` by default, and the default schedules are `16:15` for Gmail ingest, `16:25` for source ingest, and `17:00` for delivery in Pacific time.
- Open risks: The cron timezone line depends on a cron implementation that supports `CRON_TZ`; most modern Linux cron setups do, but very old or unusual cron environments may need a fallback to explicit UTC-converted schedules.
- Next recommended task: none; `T25` is complete.

### 2026-03-21 - T26 reverted the newsletter UX redesign
- Context: Rolled the digest and preview presentation back to the pre-T23 layout after the redesigned version proved unpopular, while keeping the later cached-daily-newsletter and deployment work intact.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/pipeline.py`, `curator/rendering.py`, `templates/digest.html`, `templates/digest_preview.html`
- Tests run: `uv run pytest tests/integration/test_admin_preview_renders_digest.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_delivery_uses_repository_not_live_fetch.py -q`
- Outcome: The newsletter and preview are back on the prior rendering treatment, and the shared preview/delivery paths still work with persisted daily newsletters.
- Open risks: The original rendering is plainer and less informative than the reverted redesign, but it is the requested baseline. Third-party `httplib2` deprecation warnings still appear during test startup.
- Next recommended task: none; `T26` is complete.

### 2026-03-22 - Planned next-wave tasks T27 through T32
- Context: Captured the next feature wave in the harness before implementation starts, with explicit acceptance criteria for newsletter UX quality, job orchestration, telemetry, analytics, and persona behavior hardening.
- Files changed: `agent_tasks.json`, `agent_progress.md`
- Tests run: none; planning-only harness update
- Outcome: Added pending tasks `T27` through `T32` to the harness. `T27` now explicitly replaces the low-fidelity SVG mockups with high-fidelity HTML or template-backed explorations and calls out the current failures around ugly fonts and broken wrapping so they are treated as acceptance issues rather than subjective polish.
- Open risks: Theme direction is not chosen yet, and the current mockups are below the desired aesthetic bar; implementation should not start with those assets as a visual reference.
- Next recommended task: `T27` Create high-fidelity newsletter theme explorations that clear the aesthetic and rendering bar.

### 2026-03-22 - T27 replaced the SVG pass with high-fidelity HTML theme explorations
- Context: Reworked the theme exploration assets after the earlier SVG concepts failed on typography and wrapping, and moved the exploration closer to the real email and preview constraints.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `docs/theme-mockups/index.html`, `docs/theme-mockups/theme-preview.css`, `docs/theme-mockups/option-a-financial-briefing.html`, `docs/theme-mockups/option-b-terminal-executive.html`, `docs/theme-mockups/option-c-magazine-ledger.html`, `docs/theme-mockups/option-d-research-memo.html`, `docs/theme-mockups/option-e-market-tape.html`, `tests/integration/test_newsletter_theme_options_render.py`
- Tests run: `uv run pytest tests/integration/test_newsletter_theme_options_render.py -q`
- Outcome: The repo now has five HTML-based theme explorations with email-safe font stacks, bounded headline widths, explicit wrapping rules, timestamp placement on story cards, and a shared stylesheet that is much closer to the real newsletter surface than the rejected SVG pass.
- Open risks: The old SVG files are still present as stale artifacts and can be removed in a later cleanup; the user still needs to choose a direction before the real renderer can be updated in `T28`.
- Next recommended task: `T28` Implement the chosen newsletter UX across preview and delivered email and add article timestamps.

### 2026-03-22 - T28 implemented Option E across preview and delivered email
- Context: Applied the user-selected Market Tape direction to the real digest renderer, not just the mockups, and added per-story published timestamps with explicit dark-mode support for browser preview and email surfaces.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/pipeline.py`, `curator/rendering.py`, `curator/sources.py`, `templates/digest.html`, `templates/digest_preview.html`, `docs/theme-mockups/option-e-market-tape-dark.html`, `tests/integration/test_newsletter_rendering_selected_theme.py`, `tests/integration/test_admin_preview_renders_digest.py`, `tests/integration/test_delivery_uses_repository_not_live_fetch.py`, `tests/integration/test_smoke_offline_pipeline.py`, `tests/integration/test_full_two_job_pipeline.py`, `tests/integration/test_gmail_ingest_then_delivery_from_db.py`, `tests/integration/test_legacy_equivalent_delivery.py`
- Tests run: `uv run pytest tests/integration/test_newsletter_rendering_selected_theme.py tests/integration/test_admin_preview_renders_digest.py tests/integration/test_delivery_uses_repository_not_live_fetch.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_smoke_offline_pipeline.py -q`; `uv run pytest tests/integration -q`
- Outcome: The shared digest HTML now uses the selected Option E visual language, timestamps render on story cards for repository-backed stories, preview styling aligns with the chosen theme, and the digest carries dark-mode hooks for Chrome-style preview plus email dark-mode selectors including `prefers-color-scheme` and `[data-ogsc]`.
- Open risks: Dark-mode handling in Gmail remains a best-effort compatibility layer rather than a perfectly controllable rendering surface, so real client screenshots should still be verified later. The stale SVG mockups are still present in `docs/theme-mockups/`.
- Next recommended task: `T29` Consolidate fetch and delivery into a single daily orchestrator and update bootstrap scheduling.

### 2026-03-22 - T29 consolidated scheduled fetch and delivery behind one daily orchestrator
- Context: Replaced the three-cron production schedule with one daily orchestrator while preserving the individual fetch and delivery entrypoints for manual debugging and backfills.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/jobs.py`, `daily_pipeline.py`, `scripts/bootstrap_server.py`, `README.md`, `tests/integration/test_daily_orchestrator_runs_fetch_and_delivery.py`, `tests/integration/test_deployment_bootstrap_assets.py`
- Tests run: `uv run pytest tests/integration/test_daily_orchestrator_runs_fetch_and_delivery.py tests/integration/test_deployment_bootstrap_assets.py -q`; `uv run pytest tests/integration -q`
- Outcome: The repo now has a single `daily_pipeline.py` production entrypoint, bootstrap-generated cron assets schedule only `run_daily_pipeline.sh`, and the orchestrator records stage-level results for Gmail ingest, source ingest, and delivery while keeping the old scripts available for operators.
- Open risks: The orchestrator currently attempts delivery even if one fetch stage fails, which is resilient but should be monitored in production logs to ensure partial-failure behavior matches operator expectations.
- Next recommended task: `T30` Add newsletter open and click telemetry foundations.

### 2026-03-22 - T30 added newsletter telemetry foundations
- Context: Added repository-backed telemetry primitives so delivered newsletters can record opens and tracked link clicks without breaking the cached daily-newsletter flow or polluting preview traffic.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `README.md`, `admin_app.py`, `curator/config.py`, `curator/jobs.py`, `curator/pipeline.py`, `curator/repository.py`, `curator/telemetry.py`, `main.py`, `scripts/bootstrap_server.py`, `tests/integration/test_deployment_bootstrap_assets.py`, `tests/integration/test_newsletter_telemetry_tracking_endpoints.py`, `tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py`
- Tests run: `uv run pytest tests/integration/test_newsletter_telemetry_tracking_endpoints.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py -q`; `uv run pytest tests/integration -q`
- Outcome: Delivery now persists open-token and tracked-link metadata for stored daily newsletters, sent HTML rewrites article URLs and appends an open pixel when telemetry is enabled, admin endpoints record open and click events, and deployment assets now carry a public base URL so tracked links can resolve correctly in production.
- Open risks: Preview intentionally stays untracked, so operators must validate telemetry using the delivery path rather than `/preview`. Telemetry accuracy still depends on `tracking.base_url` or `CURATOR_PUBLIC_BASE_URL` being set correctly, and email-open counts remain approximate because client-side image proxying and prefetching can distort them.
- Next recommended task: `T31` Add an admin analytics page for aggregated newsletter open and click stats.

### 2026-03-22 - T31 added an admin analytics page for newsletter telemetry
- Context: Built the operator-facing reporting layer on top of the telemetry schema so admins can inspect opens, clicks, CTR, and top-clicked stories without leaving the existing Flask admin app.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `curator/repository.py`, `templates/admin_config.html`, `templates/analytics.html`, `templates/digest_preview.html`, `templates/story_explorer.html`, `tests/integration/test_admin_newsletter_analytics_page.py`
- Tests run: `uv run pytest tests/integration/test_admin_newsletter_analytics_page.py tests/integration/test_newsletter_telemetry_tracking_endpoints.py -q`; `uv run pytest tests/integration/test_admin_story_explorer_lists_repository_stories.py tests/integration/test_admin_preview_renders_digest.py tests/integration/test_deployment_bootstrap_assets.py -q`; `uv run pytest tests/integration -q`
- Outcome: The admin app now exposes `/analytics` with trailing-window rollups, recent-newsletter open and click summaries, CTR, and a top-clicked-stories table, all backed by repository aggregation queries and linked from the existing admin, preview, and story-explorer screens.
- Open risks: Unique-open and unique-click counts are still heuristic approximations based on IP and user-agent pairs, so forwarded traffic, privacy relays, and image proxies can blur uniqueness. CTR is intentionally defined as unique clicks divided by unique opens, which is a practical operator metric but not a delivery-system ground truth.
- Next recommended task: `T32` Harden and document how persona influences ingest scoring, ranking, and summary framing.

### 2026-03-22 - T32 hardened persona coverage across ingest, ranking, and summary framing
- Context: Tightened the persona contract so operators and tests both reflect the real pipeline: persona affects ingest triage, final ranking, and the why-this-matters framing of stored summaries.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `README.md`, `templates/admin_config.html`, `tests/integration/test_persona_influences_ranking_scoring_and_summary.py`
- Tests run: `uv run pytest tests/integration/test_persona_influences_ranking_scoring_and_summary.py tests/integration/test_persona_changes_ranking_and_summary.py -q`; `uv run pytest tests/integration -q`
- Outcome: The repo now has an integration test that exercises persona-aware ingest scoring plus delivery ranking and summary framing in one flow, and the README/admin UI now state explicitly that `persona.text` influences all three stages.
- Open risks: Persona influence still depends on prompt wording rather than a separately versioned policy layer, so future prompt rewrites should re-run the new regression test before rollout.
- Next recommended task: none; `T32` is complete.

### 2026-03-22 - T33 added preview-generation locking and in-progress UI
- Context: Prevented duplicate `/preview` generations by adding repository-backed generation state for the current newsletter date and surfacing an explicit in-progress response when another request already owns that work.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `curator/repository.py`, `templates/digest_preview.html`, `tests/integration/test_preview_generation_lock_prevents_duplicate_runs.py`
- Tests run: `uv run pytest tests/integration/test_preview_generation_lock_prevents_duplicate_runs.py tests/integration/test_admin_preview_renders_digest.py -q`; `uv run pytest tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_newsletter_telemetry_tracking_endpoints.py -q`; `uv run pytest tests/integration -q`
- Outcome: `/preview` now returns `202` with an in-progress banner and auto-refresh when a generation is already running, only one generation can own a given newsletter date at a time, and completed cached newsletters still render immediately on later requests.
- Open risks: A crashed process can leave a running preview marker behind until the 15-minute stale-lock timeout passes, which is intentional to avoid duplicate work but may delay retries briefly after hard failures.
- Next recommended task: none; `T33` is complete.

### 2026-03-22 - Planned next-wave tasks T34 through T38
- Context: Captured the next server/bootstrap and newsletter polish wave in the harness before implementation, covering idempotent deployment, preview/header refinements, timezone handling, newsletter history retention, and stronger paywall filtering.
- Files changed: `agent_tasks.json`
- Tests run: none; planning-only harness update
- Outcome: Added pending tasks `T34` through `T38` so the next sessions can stay bounded instead of mixing bootstrap behavior, rendering changes, timestamp handling, history browsing, and paywall detection in one rollout.
- Open risks: The UI and paywall fixes remain pending, so current preview/newsletter behavior still reflects the pre-T35/T36/T37/T38 state.
- Next recommended task: `T34` Make the server bootstrap idempotent and resilient to service updates and logout.

### 2026-03-22 - T34 made the server bootstrap rerunnable and linger-aware
- Context: Tightened the deployment bootstrap so rerunning it cleanly reapplies generated assets, restarts the admin service to pick up script/env changes, and can optionally enable lingering for user services that must survive SSH logout.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `README.md`, `scripts/bootstrap_server.py`, `tests/integration/test_deployment_bootstrap_assets.py`
- Tests run: `uv run pytest tests/integration/test_deployment_bootstrap_assets.py -q`; `uv run python scripts/bootstrap_server.py --help`; `uv run pytest tests/integration -q`
- Outcome: The bootstrap now supports `--enable-linger`, uses an idempotent service install path that reloads, enables, and restarts the user service on rerun, and has regression coverage for both the generated assets and the install helper behavior.
- Open risks: Enabling linger still depends on `loginctl` permissions on the host; some servers will require root or sudo for that one-time step.
- Next recommended task: `T35` Refine preview and newsletter chrome with immediate generation feedback and updated CTA copy.

### 2026-03-22 - T35 refined preview feedback and digest header/CTA chrome
- Context: Updated the shared digest header to the requested Newsletter Digest copy, changed web CTA text to Read original, and moved first-load preview generation to an immediate in-progress page backed by the existing preview lock instead of a blocking request.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `curator/rendering.py`, `templates/digest.html`, `templates/digest_preview.html`, `tests/integration/test_admin_preview_renders_digest.py`, `tests/integration/test_daily_orchestrator_runs_fetch_and_delivery.py`, `tests/integration/test_delivery_uses_repository_not_live_fetch.py`, `tests/integration/test_newsletter_rendering_selected_theme.py`, `tests/integration/test_preview_generation_lock_prevents_duplicate_runs.py`, `tests/integration/test_smoke_offline_pipeline.py`
- Tests run: `uv run pytest tests/integration/test_newsletter_rendering_selected_theme.py tests/integration/test_preview_generation_lock_prevents_duplicate_runs.py tests/integration/test_admin_preview_renders_digest.py -q`; `uv run pytest tests/integration/test_delivery_uses_repository_not_live_fetch.py tests/integration/test_daily_orchestrator_runs_fetch_and_delivery.py tests/integration/test_smoke_offline_pipeline.py -q`; `uv run pytest tests/integration -q`
- Outcome: The digest hero now reads Newsletter Digest with the requested subtitle and dynamic story count, story links render as Read original and open in a new tab on web surfaces, and the first `/preview` request returns an immediate generating state while a background thread builds the cached newsletter.
- Open risks: The new first-load preview path now depends on an in-process background thread, which is fine for the current single-process admin server but would need revisiting if the admin app moves to a multi-worker deployment model later.
- Next recommended task: `T36` Render story timestamps in local time with Pacific fallback.

### 2026-03-22 - T36 rendered local preview timestamps with Pacific fallback
- Context: Removed the hard-coded UTC newsletter timestamps by making server-rendered output fall back to Pacific time while letting the browser preview upgrade to the viewer's local timezone after load.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/rendering.py`, `templates/digest_preview.html`, `tests/integration/test_newsletter_rendering_selected_theme.py`, `tests/integration/test_admin_preview_renders_digest.py`, `tests/integration/test_delivery_uses_repository_not_live_fetch.py`
- Tests run: `uv run pytest tests/integration/test_newsletter_rendering_selected_theme.py tests/integration/test_admin_preview_renders_digest.py tests/integration/test_delivery_uses_repository_not_live_fetch.py -q`; `uv run pytest tests/integration/test_preview_generation_lock_prevents_duplicate_runs.py tests/integration/test_daily_orchestrator_runs_fetch_and_delivery.py tests/integration/test_smoke_offline_pipeline.py -q`; `uv run pytest tests/integration -q`
- Outcome: Story timestamps now render as Pacific-time fallback text in the shared newsletter HTML, preview pages expose canonical UTC ISO timestamps for client-side conversion, and the preview page upgrades those timestamps to the viewer's local timezone via browser JavaScript while preserving Pacific fallback for email and other non-JS surfaces. Added pending `T39` to commit the supplied AI strategy persona as the checked-in default config.
- Open risks: Delivered email clients cannot be upgraded to recipient-local time reliably, so email surfaces intentionally remain on the Pacific fallback rather than attempting client-local conversion.
- Next recommended task: `T37` Add a newsletter history view and apply retention to generated newsletters.

### 2026-03-22 - T37 added newsletter history browsing and retention
- Context: Added a lightweight admin browser for stored daily newsletters and extended retention cleanup so cached digests, preview locks, and telemetry rows age out instead of accumulating forever.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `curator/config.py`, `curator/jobs.py`, `curator/repository.py`, `templates/admin_config.html`, `templates/analytics.html`, `templates/digest_preview.html`, `templates/story_explorer.html`, `templates/newsletter_history.html`, `templates/newsletter_history_detail.html`, `tests/integration/test_newsletter_history_view_and_ttl.py`
- Tests run: `uv run pytest tests/integration/test_newsletter_history_view_and_ttl.py tests/integration/test_admin_preview_renders_digest.py tests/integration/test_admin_newsletter_analytics_page.py -q`
- Outcome: The admin app now exposes `/newsletters` and `/newsletters/<date>` for browsing persisted digests, delivery runs perform a newsletter-specific TTL cleanup using `database.newsletter_ttl_days`, and old cached newsletters cascade-delete their preview locks and telemetry rows cleanly under test.
- Open risks: History retention currently keys off the newsletter date rather than a user-configurable timezone boundary, so the keep-window follows the same UTC newsletter-date model as the rest of the cached digest flow.
- Next recommended task: `T38` Harden paywall detection and exclude JavaScript-blocked placeholder content.

### 2026-03-22 - T38 hardened paywall detection for blocked-placeholder pages
- Context: Strengthened the deterministic paywall filter so JavaScript-disabled and adblock-gated placeholder pages are treated as unservable content before scoring or summarization, not just traditional subscribe walls.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/content.py`, `curator/jobs.py`, `tests/integration/test_paywalled_stories_are_excluded_from_digest.py`
- Tests run: `uv run pytest tests/integration/test_paywalled_stories_are_excluded_from_digest.py tests/integration/test_fetch_sources_job_writes_repository.py tests/integration/test_gmail_ingest_then_delivery_from_db.py -q`
- Outcome: Ingest now flags JavaScript-required and adblock-required placeholder pages using title, excerpt, and article-body heuristics, blocked pages are excluded from repository persistence alongside paywalled stories, and the regression test now covers both subscription walls and JS-blocked placeholders.
- Open risks: The filter remains heuristic by design, so especially unusual blocked-page copy may still need additional markers later if a publisher changes its placeholder language significantly.
- Next recommended task: `T39` Commit the supplied AI strategy persona as the checked-in default config.

### 2026-03-22 - T39 committed the supplied AI strategy persona as the repo default
- Context: Checked the supplied reader profile into the repo's default config so new environments start with the intended ranking and summary bias instead of a blank persona.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `config.yaml`, `tests/integration/test_default_config_includes_repo_persona.py`
- Tests run: `uv run pytest tests/integration/test_default_config_includes_repo_persona.py tests/integration/test_persona_influences_ranking_scoring_and_summary.py tests/integration/test_persona_changes_ranking_and_summary.py -q`
- Outcome: The checked-in `config.yaml` now includes the supplied AI strategy persona as the default `persona.text`, and a regression test locks in the committed persona wording so fresh deployments inherit the same profile.
- Open risks: The committed persona is intentionally opinionated; operators who want a neutral or different reader profile should override `persona.text` in their own deployed config.
- Next recommended task: none; `T34` through `T39` are complete.

### 2026-03-22 - T40 added an email-safe admin preview mode
- Context: Added a second preview surface aimed at Gmail-safe email rendering, while preserving the richer browser-first preview for newsletter iteration and keeping the cached daily-newsletter path intact.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `curator/config.py`, `curator/jobs.py`, `curator/pipeline.py`, `curator/rendering.py`, `templates/digest_email_safe.html`, `templates/digest_preview.html`, `tests/integration/test_admin_preview_renders_digest.py`
- Tests run: `uv run pytest tests/integration/test_admin_preview_renders_digest.py -q`
- Outcome: The admin preview now exposes toggle buttons for the existing Market Tape preview and a new email-safe preview, cached newsletters persist `render_groups` metadata so the alternate template can be rerendered without another ranking run, and the email-safe path uses a conservative table-based HTML shell for closer Gmail behavior.
- Open risks: Delivery still sends the existing primary digest HTML; this task only adds preview visibility for the email-safe variant so the actual send template can be switched deliberately in a later rollout.
- Next recommended task: none; `T40` is complete.

### 2026-03-22 - T41 added a structured multi-signal access classifier and live-corpus evaluation
- Context: Replaced the purely phrase-based access check with a deterministic classifier that can use structured paywall metadata, DOM/access tokens, and blocked-placeholder signals, then measured it against the currently stored repository stories.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/content.py`, `curator/jobs.py`, `tests/integration/test_structured_data_paywalls_are_excluded_from_digest.py`
- Tests run: `uv run pytest tests/integration/test_structured_data_paywalls_are_excluded_from_digest.py tests/integration/test_paywalled_stories_are_excluded_from_digest.py tests/integration/test_fetch_sources_job_writes_repository.py -q`; `uv run pytest tests/integration -q`; `uv run python` live-corpus evaluation against the current repository
- Outcome: The classifier now blocks structured-data paywalls and continues to catch JavaScript-disabled/adblock placeholders, ingest persists classifier signals into snapshot metadata, and the current live repository corpus of 16 stored stories evaluated with zero false positives and zero observed false negatives. The live corpus currently contains only servable persisted stories, so the zero false-negative figure reflects that no blocked examples remained in the DB after ingest filtering.
- Open risks: The live DB evaluation is only as strong as the current stored corpus; if future publishers change markup or blocker copy, additional structured or domain-specific signals may still need to be added.
- Next recommended task: none; `T41` is complete.

### 2026-03-22 - T42 persisted the full fetched corpus for classifier evaluation
- Context: Started the agent-driven classifier improvement loop by keeping all fetched candidates in the repository, including blocked and unsummarized stories, while tightening every delivery-facing repository read to require summarized servable items explicitly.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/gmail.py`, `curator/jobs.py`, `curator/repository.py`, `curator/sources.py`, `tests/integration/test_admin_preview_renders_digest.py`, `tests/integration/test_admin_source_selection_filters_delivery.py`, `tests/integration/test_delivery_uses_repository_not_live_fetch.py`, `tests/integration/test_ingest_only_persists_top_twenty_summarized_articles.py`, `tests/integration/test_ingest_only_summarizes_top_twenty_scored_articles.py`, `tests/integration/test_ingest_persists_all_candidates_for_evaluation.py`, `tests/integration/test_paywalled_stories_are_excluded_from_digest.py`, `tests/integration/test_persona_changes_ranking_and_summary.py`, `tests/integration/test_structured_data_paywalls_are_excluded_from_digest.py`
- Tests run: `uv run pytest tests/integration/test_ingest_persists_all_candidates_for_evaluation.py tests/integration/test_ingest_only_persists_top_twenty_summarized_articles.py tests/integration/test_ingest_only_summarizes_top_twenty_scored_articles.py tests/integration/test_paywalled_stories_are_excluded_from_digest.py tests/integration/test_delivery_uses_repository_not_live_fetch.py -q`; `uv run pytest tests/integration/test_admin_preview_renders_digest.py tests/integration/test_admin_source_selection_filters_delivery.py tests/integration/test_persona_changes_ranking_and_summary.py tests/integration/test_structured_data_paywalls_are_excluded_from_digest.py -q`; `uv run pytest tests/integration -q`
- Outcome: Ingest now persists the full fetched corpus for later evaluation, including blocked and unsummarized candidates, while delivery readiness, Gmail/source repository collectors, and preview/delivery behavior continue to operate only on stories with stored summaries. Added `T43` through `T46` to the harness for servability metadata, agent labeling, periodic metrics, and classifier replay.
- Open risks: Repository growth will increase until the next tasks add explicit servability metadata, evaluation storage, and a review/reporting loop; T42 only creates the raw corpus needed for that later analysis.
- Next recommended task: `T43` Persist explicit servability status, blocked reasons, detector version, and classifier signals.

### 2026-03-22 - T48 added a local Gmail lab preview surface
- Context: Added a Gmail-focused local preview mode so the admin UI can approximate a narrow mobile Gmail inspection flow without requiring you to send a test email to a phone.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `templates/digest_preview.html`, `tests/integration/test_admin_preview_renders_digest.py`
- Tests run: `uv run pytest tests/integration/test_admin_preview_renders_digest.py -q`; `uv run pytest tests/integration -q`
- Outcome: `/preview?template=gmail_lab` now shows the currently sent template and the email-safe alternative side by side in mobile-width frames, with explicit copy that it is a Gmail-focused approximation rather than a perfect Gmail renderer.
- Open risks: This lab helps catch containment and hierarchy issues locally, but Gmail app dark-mode rewriting is still only approximated; the actual delivery template is unchanged and still uses the richer sent HTML unless switched later.
- Next recommended task: none; `T48` is complete.

### 2026-03-22 - T49 shared newsletter content across cached preview and delivery
- Context: Removed the last coupling between cached newsletters and a single stored HTML variant by persisting template-independent newsletter content, then re-rendering different frontend templates from that shared payload for admin preview and email delivery.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `curator/jobs.py`, `curator/repository.py`, `tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py`
- Tests run: `uv run pytest tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_admin_preview_renders_digest.py -q`; `uv run pytest tests/integration/test_newsletter_history_view_and_ttl.py tests/integration/test_delivery_uses_repository_not_live_fetch.py tests/integration/test_full_two_job_pipeline.py -q`
- Outcome: `daily_newsletters` now stores a first-class `content` payload, delivery caches and sends the email-safe HTML, and the admin preview renders the market-tape or email-safe variants from the same stored content without another LLM call on cache hits.
- Open risks: Existing cached newsletters created before this schema change will still fall back to their stored HTML until they are regenerated under the new code; the richer browser preview still depends on `render_groups` remaining backward-compatible with future template changes.
- Next recommended task: none; `T49` is complete.

### 2026-03-22 - T50 gated schema resets and added an empty preview state
- Context: Removed the last silent data-loss path by making schema resets explicit opt-in only, and improved the admin preview so an empty repository shows a clear fetch-first message instead of kicking off a doomed generation run.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `curator/config.py`, `curator/jobs.py`, `curator/repository.py`, `tests/integration/test_admin_preview_empty_repository_shows_message.py`, `tests/integration/test_preview_generation_lock_prevents_duplicate_runs.py`, `tests/integration/test_repository_schema_bootstrap_after_reset.py`
- Tests run: `uv run pytest tests/integration/test_repository_schema_bootstrap_after_reset.py tests/integration/test_admin_preview_empty_repository_shows_message.py tests/integration/test_preview_generation_lock_prevents_duplicate_runs.py -q`; `uv run pytest tests/integration/test_admin_preview_renders_digest.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_delivery_uses_repository_not_live_fetch.py -q`
- Outcome: Schema mismatches now raise an explicit error unless `database.allow_schema_reset=true` or `CURATOR_ALLOW_SCHEMA_RESET=1` is set, and `/preview` now short-circuits with a sensible "run the fetch job" message when no delivery-ready stories exist, without calling `preview_job` or the LLM.
- Open risks: Operators with existing old-schema databases will need to opt in once if they truly want a destructive reset; the admin app still reports repository init failures generically rather than rendering the exact schema mismatch reason.
- Next recommended task: none; `T50` is complete.

### 2026-03-22 - T51 normalized Gmail source names for display
- Context: Trimmed verbose Gmail sender strings so newsletter and admin surfaces show the sender display name without the angle-bracket email suffix.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `curator/gmail.py`, `tests/integration/test_admin_story_explorer_lists_repository_stories.py`, `tests/integration/test_title_extraction_avoids_generic_read_more_titles.py`
- Tests run: `uv run pytest tests/integration/test_title_extraction_avoids_generic_read_more_titles.py tests/integration/test_admin_story_explorer_lists_repository_stories.py tests/integration/test_admin_preview_renders_digest.py -q`
- Outcome: Gmail stories now use a normalized source name like `TechCrunch Week in Review` instead of `TechCrunch Week in Review <newsletters@techcrunch.com>`, and the story explorer also normalizes older Gmail rows already stored in the repository.
- Open risks: This normalizer assumes standard `Name <email>` formatting; unusual sender headers without a parseable display name still fall back to the email address or raw header text.
- Next recommended task: none; `T51` is complete.

### 2026-03-22 - T52 switched bootstrap cron defaults to fixed UTC
- Context: Changed the generated cron defaults to fixed UTC times because the target host appears to ignore `CRON_TZ`, which made the Pacific-time schedule unreliable.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `README.md`, `scripts/bootstrap_server.py`, `tests/integration/test_deployment_bootstrap_assets.py`
- Tests run: `uv run pytest tests/integration/test_deployment_bootstrap_assets.py -q`; `uv run python scripts/bootstrap_server.py --help`
- Outcome: The generated cron file now defaults to `15 23 * * *` without `CRON_TZ`, which is deterministic on UTC hosts, and the README now explains that fixed UTC does not automatically follow DST.
- Open risks: Fixed UTC scheduling will drift relative to Pacific wall-clock time across DST boundaries, so operators must adjust the schedule manually if they want a different seasonal mapping.
- Next recommended task: none; `T52` is complete.

### 2026-03-25 - T53 introduced a shared editorial UX system across digest and admin
- Context: Reworked the digest and admin app as one coherent editorial product instead of a collection of utility pages, then ran screenshot-based UX review passes against the rendered HTML before closing the task.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/rendering.py`, `templates/admin_base.html`, `templates/admin_config.html`, `templates/analytics.html`, `templates/digest.html`, `templates/digest_email_safe.html`, `templates/digest_preview.html`, `templates/newsletter_history.html`, `templates/newsletter_history_detail.html`, `templates/story_explorer.html`, `tests/integration/test_admin_config_page_uses_shared_shell.py`, `tests/integration/test_admin_newsletter_analytics_page.py`, `tests/integration/test_admin_preview_renders_digest.py`, `tests/integration/test_admin_source_selection_filters_delivery.py`, `tests/integration/test_admin_story_explorer_lists_repository_stories.py`, `tests/integration/test_newsletter_history_view_and_ttl.py`, `tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py`
- Tests run: `uv run pytest tests/integration/test_admin_config_page_uses_shared_shell.py tests/integration/test_admin_preview_renders_digest.py tests/integration/test_admin_newsletter_analytics_page.py tests/integration/test_admin_story_explorer_lists_repository_stories.py tests/integration/test_newsletter_history_view_and_ttl.py -q`; `uv run pytest tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_admin_source_selection_filters_delivery.py tests/integration/test_delivery_uses_repository_not_live_fetch.py tests/integration/test_admin_preview_empty_repository_shows_message.py -q`; `uv run pytest tests/integration/test_admin_preview_renders_digest.py tests/integration/test_newsletter_history_view_and_ttl.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py -q`
- Outcome: The admin app now shares one editorial shell and navigation system across control, preview, archive, analytics, and story inventory; the digest and email-safe output now use the same operator-style visual language; and a screenshot-based sub-agent review cleared the final preview-readability blocker after the iframe preview fix.
- Open risks: Cached market-tape previews still depend on the stored HTML unless the richer browser-first preview is re-rendered from stored render groups, so there is room for a follow-on task to make cached preview behavior fully match the new design intent.
- Next recommended task: `T54` Restore true browser-first cached previews and harden screenshot QA for digest variants.

### 2026-03-25 - T54 restored browser-first cached previews and added a review-pack workflow
- Context: Removed the cached-preview dependency on stored delivery HTML when richer stored render groups already exist, then packaged the digest and admin surfaces into a one-command local screenshot review flow and ran a screenshot-based sub-agent UX pass against that pack.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `README.md`, `scripts/render_preview_review_pack.py`, `tests/integration/test_admin_preview_renders_digest.py`, `tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py`, `tests/integration/test_render_preview_review_pack.py`
- Tests run: `uv run pytest tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_admin_preview_renders_digest.py -q`; `uv run pytest tests/integration/test_render_preview_review_pack.py tests/integration/test_admin_preview_empty_repository_shows_message.py tests/integration/test_delivery_uses_repository_not_live_fetch.py -q`; `uv run python scripts/render_preview_review_pack.py --help`; `uv run python scripts/render_preview_review_pack.py --config-path /tmp/t54-review.YeJQry/config.yaml --newsletter-date 2026-03-25 --output-dir /tmp/t54-review.YeJQry/pack`
- Outcome: Cached `/preview` now renders the browser-first market-tape digest directly from stored `render_groups`, cached email-safe preview still uses the email-safe rendering, older stored newsletters can still fall back to `html_body` when `render_groups` are absent, and the repo now has a macOS Quick Look review-pack script that regenerates HTML fixtures plus screenshots for digest and admin surfaces in one step.
- Open risks: The review-pack helper is intentionally macOS-specific because it depends on `qlmanage`, and older stored newsletters without `render_groups` still fall back to their stored HTML rather than reconstructed browser markup.
- Next recommended task: `T55` Polish admin empty, loading, and narrow-screen states under the new shell.

### 2026-03-25 - T55 polished admin saved, empty, loading, and narrow-screen states
- Context: Tightened the editorial shell so saved, empty, and in-progress states read like deliberate product surfaces instead of utility banners, then added mobile-friendly table stacking and ran a second screenshot-based sub-agent review against the new state pack.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `templates/admin_base.html`, `templates/admin_config.html`, `templates/analytics.html`, `templates/digest_preview.html`, `templates/newsletter_history.html`, `templates/story_explorer.html`, `tests/integration/test_admin_preview_empty_repository_shows_message.py`, `tests/integration/test_admin_source_selection_filters_delivery.py`, `tests/integration/test_newsletter_history_view_and_ttl.py`
- Tests run: `uv run pytest tests/integration/test_admin_preview_empty_repository_shows_message.py tests/integration/test_newsletter_history_view_and_ttl.py tests/integration/test_admin_source_selection_filters_delivery.py -q`; `uv run pytest tests/integration/test_admin_config_page_uses_shared_shell.py tests/integration/test_admin_newsletter_analytics_page.py tests/integration/test_admin_story_explorer_lists_repository_stories.py tests/integration/test_admin_preview_renders_digest.py tests/integration/test_preview_generation_lock_prevents_duplicate_runs.py -q`; `uv run python - <<'PY' ... # wrote /tmp/t55-review.WayEZe/html state fixtures`; `qlmanage -t -s 1600 -o /tmp/t55-review.WayEZe/screens /tmp/t55-review.WayEZe/html/*.html`
- Outcome: The control room now surfaces saved and no-source states with explicit next actions, the briefing desk renders clearer empty and loading states, archive/analytics/signals empty states use the same editorial shell instead of muted one-liners, and narrow screens now stack command actions and convert dense tables into labeled card rows. A follow-up screenshot review cleared the dark-mode and mobile-state fixes as non-blocking.
- Open risks: The empty-state pages now share a very consistent cadence, which is coherent but still somewhat templated; future UX polish could differentiate Archive, Analytics, and Signals a bit more. Some secondary labels and ghost controls in dark mode could still take a small contrast lift.
- Next recommended task: `T43` Persist explicit servability status, blocked reasons, detector version, and classifier signals.

### 2026-03-25 - Hotfix salvaged malformed summary JSON before it reaches readers
- Context: User-reported a shipped digest item that rendered as `Untitled` plus a raw JSON blob after the summary model returned malformed JSON with an invalid escape sequence.
- Files changed: `agent_progress.md`, `curator/llm.py`, `tests/integration/test_malformed_summary_json_is_salvaged.py`, `tests/integration/test_preview_uses_ingest_summaries_without_summary_llm.py`
- Tests run: `uv run pytest tests/integration/test_malformed_summary_json_is_salvaged.py tests/integration/test_preview_uses_ingest_summaries_without_summary_llm.py tests/integration/test_fetch_sources_job_writes_repository.py -q`; `uv run pytest tests/integration/test_admin_preview_renders_digest.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py -q`
- Outcome: Summary parsing now salvages near-valid JSON, including invalid escapes like `\$`, before falling back to raw text, so malformed model output no longer ships as `Untitled` with a raw `{"headline": ...}` body. The regression test covers both ingest persistence and preview reuse.
- Open risks: Truly malformed summaries that cannot be recovered structurally still fall back to raw text; that is safer than the previous behavior, but a later hardening pass could add stricter rejection or retry behavior.
- Next recommended task: `T43` Persist explicit servability status, blocked reasons, detector version, and classifier signals.

### 2026-03-25 - Visual rollback restored the earlier green palette without changing IA
- Context: User requested the newer beige/blue editorial palette be reverted while keeping the improved information architecture from the recent UX work intact.
- Files changed: `agent_progress.md`, `curator/rendering.py`, `templates/admin_base.html`, `templates/digest.html`, `templates/digest_email_safe.html`
- Tests run: `uv run pytest tests/integration/test_admin_preview_renders_digest.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py -q`; `uv run pytest tests/integration/test_admin_config_page_uses_shared_shell.py tests/integration/test_admin_newsletter_analytics_page.py tests/integration/test_newsletter_history_view_and_ttl.py -q`
- Outcome: The admin shell, browser digest, and email-safe digest now use the earlier green palette again while preserving the current layout, hierarchy, empty states, and preview behavior.
- Open risks: This rollback targets the primary palette only; if further visual tuning is needed, the remaining typography and spacing decisions still reflect the newer editorial UX pass.
- Next recommended task: `T43` Persist explicit servability status, blocked reasons, detector version, and classifier signals.

### 2026-03-26 - Telemetry defaults now require explicit opt-in for redirect tracking
- Context: Disabled delivery-time click/open tracking by default so server-side digest sends no longer emit broken `/track/*` redirects when the admin app is not publicly serving telemetry endpoints.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `README.md`, `config.yaml`, `curator/config.py`, `curator/telemetry.py`, `main.py`, `scripts/bootstrap_server.py`, `tests/integration/test_deployment_bootstrap_assets.py`, `tests/integration/test_delivery_tracking_disabled_by_default.py`, `tests/integration/test_newsletter_telemetry_tracking_endpoints.py`, `tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py`
- Tests run: `uv run pytest tests/integration/test_deployment_bootstrap_assets.py tests/integration/test_newsletter_telemetry_tracking_endpoints.py tests/integration/test_delivery_tracking_disabled_by_default.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py -q`
- Outcome: Tracking is now disabled unless explicitly enabled through config or bootstrap-generated env, generated server assets carry `CURATOR_ENABLE_TELEMETRY`, and delivery leaves original article URLs untouched by default while still supporting tracked redirects when opted in.
- Open risks: Operators who do want tracking must rerun bootstrap or update the generated env to set `CURATOR_ENABLE_TELEMETRY=1`, otherwise analytics endpoints will remain inactive for sent digests.
- Next recommended task: `T56` Add a CLI dry-run delivery mode that sends the digest only to an explicit test recipient.

### 2026-03-26 - T56 added a dry-run delivery recipient override for end-to-end testing
- Context: Added an operator-facing way to send the current digest to exactly one explicit inbox without editing config recipients or touching the live Buttondown list.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `README.md`, `deliver_digest.py`, `main.py`, `scripts/bootstrap_server.py`, `tests/integration/test_deliver_digest_dry_run_recipient_override.py`, `tests/integration/test_deployment_bootstrap_assets.py`
- Tests run: `uv run pytest tests/integration/test_deliver_digest_dry_run_recipient_override.py -q`; `uv run pytest tests/integration/test_deployment_bootstrap_assets.py tests/integration/test_buttondown_recipient_resolution.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py -q`
- Outcome: `deliver_digest.py` now accepts `--dry-run-recipient`, the override bypasses Buttondown and config recipients while still using the normal delivery pipeline, and generated wrapper scripts now forward CLI arguments so `run_deliver_digest.sh --dry-run-recipient you@example.com` works on the server.
- Open risks: The override currently trusts the CLI input as-is and only trims whitespace, so invalid email strings will still make it down to the Gmail send path.
- Next recommended task: `T43` Persist explicit servability status, blocked reasons, detector version, and classifier signals.

### 2026-03-28 - T57 quiesced the admin service around the generated daily wrapper
- Context: Started the new subscriber-personalization feature wave with the production unblocker first, keeping the RAM-saving stop/start logic in the generated server wrapper rather than inside the Python pipeline.
- Files changed: `agent_spec.md`, `agent_contracts/T57_admin_service_orchestration.md`, `agent_tasks.json`, `agent_progress.md`, `scripts/bootstrap_server.py`, `tests/integration/test_deployment_bootstrap_assets.py`
- Tests run: `python3 -m json.tool agent_tasks.json >/dev/null`; `uv run pytest tests/integration/test_deployment_bootstrap_assets.py -q`
- Outcome: The bootstrap now emits `CURATOR_ADMIN_SERVICE_NAME` and `CURATOR_PAUSE_ADMIN_DURING_DAILY`, generated `run_daily_pipeline.sh` stops the configured `systemd --user` admin service before running `daily_pipeline.py`, and trap-based cleanup restarts it on success, non-zero exit, and already-stopped-service scenarios while preserving the pipeline exit code.
- Open risks: Signal-interruption cleanup is statically asserted in the generated wrapper tests rather than exercised with a live `SIGINT` or `SIGTERM`.
- Next recommended task: `T58` Add subscriber login and session storage in SQLite.

### 2026-03-28 - T58 added passwordless subscriber login and SQLite-backed sessions
- Context: Established the first subscriber-facing auth layer in the existing Flask app so per-user settings can land on a real account model instead of piggybacking on operator auth or Buttondown metadata.
- Files changed: `agent_contracts/T58_subscriber_login_and_session.md`, `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `curator/repository.py`, `templates/admin_base.html`, `templates/subscriber_login.html`, `templates/subscriber_account.html`, `tests/integration/test_subscriber_login_and_session_flow.py`
- Tests run: `uv run pytest tests/integration/test_subscriber_login_and_session_flow.py -q`; `uv run pytest tests/integration/test_admin_config_page_uses_shared_shell.py -q`
- Outcome: The app now supports passwordless subscriber login through one-time magic links, stores only hashed login and session tokens in SQLite, attempts Gmail-backed login email delivery when credentials are available, exposes a debug or offline fallback link path for local verification, and keeps subscriber sessions separate from `CURATOR_ADMIN_TOKEN` operator auth.
- Open risks: The live login-email path still depends on the server's Gmail OAuth token setup; a misconfigured mail environment will not send links unless the operator enables the debug or offline fallback path.
- Next recommended task: `T59` Add subscriber settings persistence for persona text and preferred sources.

### 2026-03-28 - T59 added subscriber settings persistence on top of the new session layer
- Context: Extended the new subscriber account system with a real settings surface so persona text and preferred-source choices now persist in SQLite without switching delivery reads yet.
- Files changed: `agent_contracts/T59_subscriber_settings_persistence.md`, `agent_tasks.json`, `agent_progress.md`, `admin_app.py`, `curator/repository.py`, `templates/subscriber_login.html`, `templates/subscriber_account.html`, `templates/subscriber_settings.html`, `tests/integration/test_subscriber_settings_page_persists_profile.py`
- Tests run: `uv run pytest tests/integration/test_subscriber_settings_page_persists_profile.py -q`; `uv run pytest tests/integration/test_subscriber_login_and_session_flow.py -q`; `uv run pytest tests/integration/test_admin_config_page_uses_shared_shell.py -q`
- Outcome: Subscribers can now open `/settings`, save trimmed persona text plus canonical preferred-source selections into a new `subscriber_profiles` table, and keep admin-disabled sources visible as unavailable without silently dropping them from the saved profile.
- Open risks: Delivery still ignores the new DB-backed subscriber profile data until `T60`, so settings persistence exists ahead of delivery adoption by design.
- Next recommended task: `T60` Switch delivery personalization to DB-backed profiles and append the signup CTA.

### 2026-03-28 - T60 switched delivery personalization to DB-backed profiles and added the signup CTA
- Context: Moved delivery personalization reads onto SQLite-backed subscriber profiles while preserving Buttondown-first recipient selection, then appended the Buttondown signup CTA exactly once across fresh and cached email sends.
- Files changed: `agent_contracts/T60_db_backed_delivery_and_signup_cta.md`, `agent_tasks.json`, `agent_progress.md`, `curator/jobs.py`, `curator/repository.py`, `main.py`, `tests/integration/test_delivery_personalizes_by_subscriber_profile.py`, `tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py`, `tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py`, `tests/integration/test_newsletter_footer_signup_cta.py`
- Tests run: `uv run pytest tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py tests/integration/test_newsletter_footer_signup_cta.py -q`; `uv run pytest tests/integration/test_delivery_personalizes_by_subscriber_profile.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_buttondown_recipient_resolution.py tests/integration/test_deliver_digest_dry_run_recipient_override.py -q`; `git diff --check`
- Outcome: Delivery now resolves per-recipient persona text and preferred-source filters from SQLite before Buttondown or YAML fallbacks, dry-run overrides also respect DB profiles, fresh newsletters persist the signup CTA in both text and HTML, and pre-rollout cached newsletter rows are decorated at send time without mutating storage.
- Open risks: Delivery still reads all subscriber delivery profiles up front before matching the resolved recipients, which is fine for the current scale but may be worth tightening in the final cleanup pass if the subscriber list grows.
- Next recommended task: `T61` Restrict persona to final selection and widen initial discovery recall.

### 2026-03-28 - T61 restricted persona to final selection and widened discovery recall
- Context: Tightened persona handling so only the final delivery ranking prompt sees it, then raised the global discovery defaults just enough to pull in more upstream candidates without changing downstream newsletter size.
- Files changed: `agent_contracts/T61_persona_and_discovery_tuning.md`, `agent_tasks.json`, `agent_progress.md`, `curator/config.py`, `curator/prompts.py`, `curator/dev.py`, `curator/jobs.py`, `main.py`, `tests/integration/test_persona_changes_ranking_and_summary.py`, `tests/integration/test_persona_only_affects_final_selection.py`, `tests/integration/test_discovery_fetch_budget_increases_recall.py`
- Tests run: `uv run pytest tests/integration/test_persona_only_affects_final_selection.py tests/integration/test_discovery_fetch_budget_increases_recall.py -q`; `uv run pytest tests/integration/test_persona_changes_ranking_and_summary.py tests/integration/test_gmail_prefetch_scoring_limits_article_fetches.py tests/integration/test_ingest_only_summarizes_top_twenty_scored_articles.py tests/integration/test_ingest_only_persists_top_twenty_summarized_articles.py -q`; `git diff --check`
- Outcome: Persona text now only influences `select_top_stories`, ingest scoring and summaries are persona-neutral, the default additional-source discovery cap increased from `20` to `30`, the Gmail fetch-after-score cap increased from `12` to `18`, and the final newsletter size plus source quotas stayed unchanged.
- Open risks: Existing operator YAML overrides still win over the new defaults, so some deployed instances will not see the wider discovery budget until their configs are refreshed or the cleanup sprint explicitly migrates them.
- Next recommended task: `T62` Compatibility cleanup and rollout for subscriber personalization.

### 2026-03-28 - T62 removed legacy personalization reads and documented the rollout
- Context: Finalized the subscriber-personalization migration by making SQLite the only personalization source, while keeping recipient discovery safe through the existing Buttondown/config fallback order.
- Files changed: `agent_contracts/T62_subscriber_personalization_cleanup.md`, `agent_tasks.json`, `agent_progress.md`, `curator/config.py`, `curator/jobs.py`, `README.md`, `tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py`, `tests/integration/test_delivery_personalizes_by_subscriber_profile.py`, `tests/integration/test_personalized_newsletter_cache_keys_by_profile.py`, `tests/integration/test_buttondown_recipient_resolution.py`, `tests/integration/test_deliver_digest_dry_run_recipient_override.py`
- Tests run: `uv run pytest tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py tests/integration/test_subscriber_settings_page_persists_profile.py -q`; `uv run pytest tests/integration/test_buttondown_recipient_resolution.py tests/integration/test_deliver_digest_dry_run_recipient_override.py tests/integration/test_delivery_personalizes_by_subscriber_profile.py tests/integration/test_personalized_newsletter_cache_keys_by_profile.py -q`
- Outcome: Delivery now personalizes only from SQLite-backed subscriber profiles, auto-upserts bare recipient rows during sends, ignores Buttondown metadata plus legacy YAML subscriber overrides for personalization, and documents rollout verification plus rollback steps in the README.
- Open risks: Delivery now ignores legacy `config.yaml` `subscribers` blocks entirely, so operators who still maintain those blocks must remove them manually; the repo documents that change but does not rewrite existing config files automatically.
- Next recommended task: none from this feature wave; `T57` through `T62` are complete.

### 2026-03-28 - T63 exposed a read-only recent-story MCP server over stdio
- Context: Started the new MCP feature wave on a separate worktree branch by shipping a real end-to-end vertical slice first instead of only planning scaffolding.
- Files changed: `agent_spec.md`, `agent_tasks.json`, `agent_progress.md`, `agent_contracts/T63_recent_story_feed_mcp_server.md`, `curator/story_feed.py`, `curator/mcp_server.py`, `scripts/newsletter_mcp_server.py`, `tests/integration/test_mcp_recent_story_feed_server.py`
- Tests run: `uv run pytest tests/integration/test_mcp_recent_story_feed_server.py -q`; `git diff --check`
- Outcome: The repo now has a newline-delimited stdio MCP server that supports `initialize`, `tools/list`, `ping`, and `tools/call`, exposes exactly one read-only `list_recent_stories` tool, reads the existing SQLite repository in read-only mode, and returns metadata-only stories from the last 24 hours with deterministic ordering and no fresh retrieval or summarization.
- Open risks: The transport is a thin custom JSON-RPC implementation tuned to the current MCP stdio contract, so future client-compatibility changes should be revalidated if the project later adds another MCP transport or swaps to an SDK.
- Next recommended task: `T64` Document and smoke-test the MCP server launch path.

### 2026-03-28 - T64 documented the MCP launch path and added smoke coverage
- Context: Tightened the new MCP server into a usable operator surface by documenting the checked-in launch command and making the entrypoint self-describing without reopening the story-feed semantics.
- Files changed: `README.md`, `agent_tasks.json`, `agent_progress.md`, `agent_contracts/T64_mcp_launch_docs_and_smoke.md`, `curator/mcp_server.py`, `scripts/newsletter_mcp_server.py`, `tests/integration/test_mcp_story_feed_help.py`
- Tests run: `uv run pytest tests/integration/test_mcp_story_feed_help.py -q`; `uv run pytest tests/integration/test_mcp_recent_story_feed_server.py -q`; `git diff --check`
- Outcome: The MCP server now has a thin CLI wrapper with `--help` and optional `--config-path`, the README documents the exact read-only stdio launch path and config expectations, and the new smoke test proves the checked-in entrypoint is callable locally and can answer `initialize` offline.
- Open risks: This sprint intentionally avoids re-testing `tools/list` and `tools/call`; those semantics remain covered by the T63 integration test and should be rerun if the launch wrapper grows beyond config selection.
- Next recommended task: `T65` Add optional query ergonomics to the recent-story MCP tool.

### 2026-03-28 - T65 added bounded query ergonomics and queued publish plus Codex tasks
- Context: Kept the next MCP sprint narrowly focused on practical filtering for `list_recent_stories`, while also extending the harness so publish and Codex-consumption work are explicitly queued behind the stable tool contract.
- Files changed: `agent_spec.md`, `agent_tasks.json`, `agent_progress.md`, `agent_contracts/T65_mcp_story_feed_query_ergonomics.md`, `curator/story_feed.py`, `curator/mcp_server.py`, `tests/integration/test_mcp_recent_story_feed_server.py`
- Tests run: `uv run pytest tests/integration/test_mcp_recent_story_feed_server.py -q`; `uv run pytest tests/integration/test_mcp_story_feed_help.py -q`; `git diff --check`
- Outcome: `list_recent_stories` now accepts bounded `hours` and exact-match `source_type` arguments while preserving the default 24-hour behavior, invalid arguments now surface as MCP-visible tool errors, and the harness now includes follow-on tasks for publishing the MCP as a local plugin plus adding a Codex-oriented workflow on top of it.
- Open risks: The server now has a slightly larger argument surface, so any future additions should stay bounded or they will blur into pagination or discovery work that belongs in a separate sprint.
- Next recommended task: `T66` Publish the MCP server as a Codex-discoverable local plugin.

### 2026-03-28 - T66 published the MCP server as a repo-local Codex plugin
- Context: Turned the read-only MCP server into a repo-local publish surface that Codex can discover through a local marketplace entry, without changing server behavior.
- Files changed: `README.md`, `.agents/plugins/marketplace.json`, `agent_tasks.json`, `agent_progress.md`, `agent_contracts/T66_mcp_publish_and_manifest.md`, `plugins/newsletter-curator-story-feed/.codex-plugin/plugin.json`, `plugins/newsletter-curator-story-feed/.mcp.json`, `tests/integration/test_mcp_publish_manifest.py`
- Tests run: `uv run pytest tests/integration/test_mcp_publish_manifest.py -q`; `uv run pytest tests/integration/test_mcp_recent_story_feed_server.py tests/integration/test_mcp_story_feed_help.py -q`; `git diff --check`
- Outcome: The repo now publishes a local `newsletter-curator-story-feed` plugin with a real plugin manifest, a stdio `.mcp.json` that launches the checked-in server from the plugin root, a local marketplace entry under `.agents/plugins/marketplace.json`, and a manifest smoke test that proves the published plugin can negotiate `initialize` offline.
- Open risks: This publish path is repo-local, so any future home-local or global Codex installation flow still needs a separate validation step rather than assuming the same relative paths.
- Next recommended task: `T67` Add a Codex agent workflow that uses the MCP story feed.

### 2026-03-28 - T67 added a Codex skill and helper for the published story-feed plugin
- Context: Added a repo-local Codex workflow on top of the published MCP plugin so agents can query stored stories through the manifest contract instead of calling repository code directly.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `agent_contracts/T67_codex_mcp_story_feed.md`, `docs/codex-mcp-story-feed.md`, `skills/codex-mcp-story-feed/SKILL.md`, `skills/codex-mcp-story-feed/agents/openai.yaml`, `skills/codex-mcp-story-feed/scripts/query_story_feed.py`, `tests/integration/test_codex_mcp_story_feed_smoke.py`
- Tests run: `uv run pytest tests/integration/test_codex_mcp_story_feed_smoke.py -q`; `uv run pytest tests/integration/test_mcp_publish_manifest.py tests/integration/test_mcp_recent_story_feed_server.py tests/integration/test_mcp_story_feed_help.py -q`; `git diff --check`
- Outcome: The repo now has a `$codex-mcp-story-feed` skill, a helper that reads `plugins/newsletter-curator-story-feed/.mcp.json`, starts the published MCP server, completes `initialize`, and calls `list_recent_stories`, plus a smoke test that proves the workflow works offline against a seeded SQLite repo.
- Open risks: The helper currently exercises the repo-local published plugin path only, so any future global Codex install flow should be tested separately rather than assuming the same relative manifest paths.
- Next recommended task: none; `T67` is complete.

### 2026-03-28 - Reverted T67 and added a production-host MCP launch contract
- Context: Removed the Codex-specific skill layer, then changed the published MCP launch path so the same read-only server can run locally by default or over SSH on the real curator host where the SQLite database actually lives.
- Files changed: `README.md`, `agent_spec.md`, `agent_tasks.json`, `agent_progress.md`, `agent_contracts/T67_codex_mcp_story_feed.md`, `docs/codex-mcp-story-feed.md`, `plugins/newsletter-curator-story-feed/.mcp.json`, `scripts/newsletter_mcp_launch.py`, `skills/codex-mcp-story-feed/SKILL.md`, `skills/codex-mcp-story-feed/agents/openai.yaml`, `skills/codex-mcp-story-feed/scripts/query_story_feed.py`, `tests/integration/test_codex_mcp_story_feed_smoke.py`, `tests/integration/test_mcp_launch_wrapper.py`, `tests/integration/test_mcp_publish_manifest.py`
- Tests run: `uv run pytest tests/integration/test_mcp_launch_wrapper.py tests/integration/test_mcp_publish_manifest.py tests/integration/test_mcp_recent_story_feed_server.py tests/integration/test_mcp_story_feed_help.py -q`; `git diff --check`
- Outcome: T67 was removed from the harness, the Codex skill artifacts were deleted, and the published plugin now launches through `scripts/newsletter_mcp_launch.py`, which preserves the local offline path but also supports `CURATOR_MCP_TARGET=ssh` so the actual MCP server can run on the production host and read that host's SQLite file locally.
- Open risks: The branch now has the correct remote-launch mechanism, but the real target still needs concrete `CURATOR_MCP_SSH_HOST`, `CURATOR_MCP_REMOTE_REPO_DIR`, and usually `CURATOR_MCP_REMOTE_CONFIG_PATH` values before it can point at the production database.
- Next recommended task: set the production SSH and path parameters for the real curator host.

### 2026-03-31 - T68 added a secure read-only debug log endpoint
- Context: Added a production-debug surface that operators can use to share bounded structured log tails with Codex without exposing arbitrary file reads or reusing the admin token.
- Files changed: `README.md`, `admin_app.py`, `agent_spec.md`, `agent_tasks.json`, `agent_progress.md`, `agent_contracts/T68_secure_debug_log_endpoint.md`, `curator/debug_logs.py`, `curator/observability.py`, `scripts/bootstrap_server.py`, `tests/integration/test_admin_debug_log_endpoint.py`, `tests/integration/test_deployment_bootstrap_assets.py`, `tests/integration/test_offline_e2e_fixture_runner.py`
- Tests run: `uv run pytest tests/integration/test_admin_debug_log_endpoint.py tests/integration/test_deployment_bootstrap_assets.py tests/integration/test_http_mcp_server.py tests/integration/test_admin_login_flow.py tests/integration/test_offline_e2e_fixture_runner.py -q`
- Outcome: Structured events can now be mirrored into `CURATOR_DEBUG_LOG_PATH`, the admin server exposes header-only `GET /debug/logs` protected by `CURATOR_DEBUG_LOG_TOKEN`, the route returns a bounded JSON tail from exactly one configured absolute file path, bootstrap writes the debug-log env wiring, and the new integration coverage locks down auth, caps, missing-config handling, and symlink rejection.
- Open risks: The endpoint returns log lines verbatim, so production operators should keep `CURATOR_DEBUG_LOG_PATH` pointed at the dedicated structured debug log file rather than a broader system log with unrelated secrets.
- Next recommended task: `T43` Persist explicit servability status, blocked reasons, detector version, and classifier signals.

### 2026-04-04 - T69 flattened final delivery rendering and removed footer CTA chrome
- Context: Simplified the final email presentation so both fresh and cached newsletters render as one flat ranked story list, then removed the extra footer CTA chrome from the canonical delivery output.
- Files changed: `admin_app.py`, `agent_spec.md`, `agent_tasks.json`, `agent_progress.md`, `agent_contracts/T69_flatten_delivery_and_remove_footer.md`, `curator/jobs.py`, `curator/pipeline.py`, `curator/rendering.py`, `scripts/run_admin_ui_e2e_harness.py`, `templates/digest.html`, `templates/digest_email_safe.html`, `tests/integration/test_admin_ui_e2e_harness.py`, `tests/integration/test_delivery_personalizes_by_subscriber_profile.py`, `tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py`, `tests/integration/test_final_delivery_flat_ranking_no_footer.py`, `tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py`
- Tests run: `uv run pytest tests/integration/test_final_delivery_flat_ranking_no_footer.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_newsletter_rendering_selected_theme.py tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py tests/integration/test_delivery_personalizes_by_subscriber_profile.py tests/integration/test_admin_ui_e2e_harness.py -q`; `git diff --check`
- Outcome: The pipeline now persists a flat ordered render payload, plain-text and HTML delivery rerender from that same canonical structure, grouped category headers are gone from final output, and the footer or signup CTA no longer appears in fresh or cached sends.
- Open risks: Older stored newsletters that lack `render_groups` still fall back to their stored body and HTML, so those rows will only fully benefit from the new renderer after they are regenerated.
- Next recommended task: `T43` Persist explicit servability status, blocked reasons, detector version, and classifier signals.

### 2026-04-04 - T70 added opt-in PDF delivery for subscriber profiles
- Context: Added a Kindle-oriented PDF delivery option on top of the existing subscriber profile and delivery pipeline without changing the default email path.
- Files changed: `admin_app.py`, `agent_spec.md`, `agent_tasks.json`, `agent_progress.md`, `agent_contracts/T70_opt_in_pdf_delivery.md`, `curator/gmail.py`, `curator/jobs.py`, `curator/pdf.py`, `curator/repository.py`, `main.py`, `pyproject.toml`, `templates/subscriber_settings.html`, `tests/fakes.py`, `tests/integration/test_buttondown_recipient_resolution.py`, `tests/integration/test_deliver_digest_dry_run_recipient_override.py`, `tests/integration/test_delivery_personalizes_by_subscriber_profile.py`, `tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py`, `tests/integration/test_subscriber_pdf_delivery_opt_in.py`, `tests/integration/test_subscriber_settings_page_persists_profile.py`, `uv.lock`
- Tests run: `uv run pytest tests/integration/test_subscriber_pdf_delivery_opt_in.py tests/integration/test_subscriber_settings_page_persists_profile.py tests/integration/test_delivery_personalizes_by_subscriber_profile.py tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py -q`; `uv run pytest tests/integration/test_subscriber_settings_page_persists_profile.py tests/integration/test_delivery_personalizes_by_subscriber_profile.py tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py tests/integration/test_buttondown_recipient_resolution.py tests/integration/test_deliver_digest_dry_run_recipient_override.py -q`; `git diff --check`
- Outcome: Subscriber profiles now persist `delivery_format` with a non-destructive SQLite migration defaulting legacy rows to `email`, `/settings` exposes an email-vs-PDF choice, opted-in readers receive a short note plus a generated PDF attachment built from canonical ranked newsletter content, and mixed-format groups stay isolated so email and PDF subscribers do not share the wrong artifact type.
- Open risks: `main.preview_job` still captures sends with a helper that does not accept attachments, so PDF-preview behavior is not covered by the current contract or tests.
- Next recommended task: `T43` Persist explicit servability status, blocked reasons, detector version, and classifier signals.

### 2026-04-04 - T71 hardened newsletter public-host links and added direct-link fallback
- Context: Investigated dead tracking behavior in delivered mail, traced it to outbound link generation falling back to localhost when no public base URL was configured, and closed the issue by making delivery degrade safely instead of emitting dead tracking links.
- Files changed: `agent_spec.md`, `agent_tasks.json`, `agent_progress.md`, `agent_contracts/T71_delivery_public_host_links_and_fallback.md`, `curator/jobs.py`, `curator/rendering.py`, `curator/telemetry.py`, `templates/digest_email_safe.html`, `tests/integration/test_delivery_public_host_links_and_fallback.py`, `tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py`
- Tests run: `uv run pytest tests/integration/test_delivery_public_host_links_and_fallback.py tests/integration/test_newsletter_telemetry_tracking_endpoints.py tests/integration/test_delivery_tracking_disabled_by_default.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_subscriber_pdf_delivery_opt_in.py -q`; `python3 -m json.tool agent_tasks.json >/dev/null`; `git diff --check`
- Outcome: Delivered newsletters now prepend a settings URL in plain text and render a header-level settings link in the email-safe HTML when a public host is configured, tracked links rewrite only the marked CTA while preserving a visible direct article fallback, and telemetry is skipped entirely when `tracking.base_url` plus `CURATOR_PUBLIC_BASE_URL` are both absent so delivery no longer emits dead localhost tracking links.
- Open risks: The admin email-safe preview route still does not pass the new `settings_url`, so preview parity with delivered email remains incomplete even though the delivery contract now passes.
- Next recommended task: `T43` Persist explicit servability status, blocked reasons, detector version, and classifier signals.

### 2026-04-19 - T73 skipped the generated daily pipeline wrapper on Sunday
- Context: Started the post-weekly-digest scheduling wave by making the generated cron wrapper no-op on Sunday, so the whole daily pipeline is skipped before API-key validation, admin-service pause, pipeline execution, or failure alerts.
- Files changed: `agent_contracts/T73_skip_sunday_pipeline.md`, `agent_spec.md`, `agent_tasks.json`, `agent_progress.md`, `scripts/bootstrap_server.py`, `tests/integration/test_deployment_bootstrap_assets.py`
- Tests run: `uv run pytest tests/integration/test_deployment_bootstrap_assets.py -q`; `uv run pytest tests/integration/test_weekend_delivery_schedule.py tests/integration/test_deployment_bootstrap_assets.py -q`; `git diff --check`
- Outcome: `run_daily_pipeline.sh` now exits 0 with `daily pipeline skipped: Sunday` when `date +%u` reports Sunday, and the regression test verifies no `systemctl`, `daily_pipeline.py`, or alert invocation happens on that path. Existing non-Sunday success, failure-alert, and admin-resume wrapper tests still pass with a deterministic fake weekday.
- Open risks: The Sunday check currently uses the system `date +%u` timezone; `T74` is queued to pin all weekday decisions to Pacific time.
- Evaluator note: A post-implementation evaluator subagent was requested, but the account hit its usage limit before it could run. The generator completed a local contract review and the listed tests passed.
- Next recommended task: `T74` Verify weekday decisions use Pacific time.

### 2026-04-19 - T74 pinned weekday decisions to Pacific time
- Context: Aligned the Python delivery scheduler and generated daily wrapper so daily, Saturday weekly, and Sunday skipped decisions are based on `America/Los_Angeles` calendar days.
- Files changed: `agent_contracts/T74_pacific_weekday_decisions.md`, `agent_tasks.json`, `agent_progress.md`, `curator/jobs.py`, `scripts/bootstrap_server.py`, `tests/integration/test_weekend_delivery_schedule.py`, `tests/integration/test_deployment_bootstrap_assets.py`
- Tests run: `uv run pytest tests/integration/test_weekend_delivery_schedule.py tests/integration/test_deployment_bootstrap_assets.py -q`; `uv run pytest`; `git diff --check`
- Outcome: `current_delivery_datetime()` now returns Pacific time, `current_newsletter_date()` follows the Pacific delivery date, `delivery_issue_type_for_datetime()` classifies after Pacific conversion, and the generated wrapper uses `TZ=America/Los_Angeles date +%u`. Boundary coverage now proves a UTC Sunday that is still Pacific Saturday runs as the weekly issue.
- Open risks: None known for scheduling; non-scheduling UTC persistence and freshness windows remain unchanged.
- Evaluator note: A separate evaluator subagent remains unavailable because the account hit its usage limit. The generator completed a local contract review and the full test suite passed.
- Next recommended task: `T75` Add a manual weekly digest override to the daily pipeline wrapper.
