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

### 2026-03-22 - T43 added first-class servability and classifier metadata
- Context: Promoted classifier details from loose snapshot metadata into first-class repository fields so every fetched candidate now carries an explicit servability state, detector version, and structured classifier signals.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `curator/content.py`, `curator/jobs.py`, `curator/repository.py`, `tests/integration/test_ingest_persists_servability_metadata.py`, `tests/integration/test_repository_schema_bootstrap_after_reset.py`
- Tests run: `uv run pytest tests/integration/test_ingest_persists_servability_metadata.py tests/integration/test_repository_schema_bootstrap_after_reset.py tests/integration/test_ingest_persists_all_candidates_for_evaluation.py tests/integration/test_paywalled_stories_are_excluded_from_digest.py -q`; `uv run pytest tests/integration -q`
- Outcome: Article snapshots now persist `servability_status`, `detector_version`, and `classifier_signals_json`; ingest records `servable`, `blocked`, or `candidate` per story; and repository reads expose parsed classifier signals alongside the existing summary and paywall fields.
- Open risks: The repository now contains the metadata needed for evaluation, but there is still no persisted agent-label layer or confusion-matrix reporting until `T44` and `T45` land.
- Next recommended task: `T44` Add an agent-driven evaluation script that labels the live repository corpus.
