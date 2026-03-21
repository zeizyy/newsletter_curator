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
