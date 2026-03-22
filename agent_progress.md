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
