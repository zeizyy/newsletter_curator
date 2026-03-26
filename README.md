# Newsletter Curator

Personal newsletter curator with a repository-first architecture: Gmail newsletters and publisher feeds are ingested into a local SQLite repository, then a daily orchestrator ranks, summarizes, and emails the digest from stored snapshots.

Subscribe to the live newsletter: <https://buttondown.com/zeizyynewsletter> to get something like this everyday:

![Example newsletter render](docs/readme-assets/newsletter-example.png)

## Features
- Separate debug-friendly ingest jobs for Gmail newsletters and additional publisher feeds
- Single daily orchestrator for production cron scheduling
- Local SQLite repository for normalized stories, article snapshots, and run history
- Admin UI for source selection and persona text
- Repo-only delivery job with no live Gmail reads or live article fetches at send time
- Two-stage LLM flow: persona-aware ingest scoring and ranking, followed by persona-aware summaries over stored article text
- Final selection quotas by source type (default: `gmail=10`, `additional_source=5`)
- Delivery readiness checks against ingest run history and stored fresh stories
- Deterministic canned-data mode for local development and integration testing

## Pipeline Design
1) `daily_pipeline.py` is the production entrypoint. It runs Gmail ingest, source ingest, then digest delivery in sequence.
2) `fetch_gmail.py` and `fetch_sources.py` remain available as manual debug or backfill entrypoints.
3) `deliver_digest.py` remains available as a manual send or cache-regeneration entrypoint.
4) Delivery reads only repository-backed stories within the configured freshness windows.
5) Delivery merges Gmail + additional-source candidates, dedupes by URL, ranks with `openai.reasoning_model`, applies source quotas, summarizes stored article text with `openai.summary_model`, and emails the digest.
6) Delivery records run metadata and warns when one source type is stale or has a failed latest ingest, but can still proceed if another source type has fresh repository data.

Runtime output includes:
- repository readiness by source type
- links retrieved from repository by source type
- ranked/final counts sliced by source type and source name
- summary completion/backfill/skip counts
- per-model token usage
- JSON output from each standalone job entrypoint

## Requirements
- Python 3.13+
- `uv` (recommended)
- Google OAuth credentials for Gmail API
- OpenAI API key

## Setup
1) Place Gmail OAuth credentials at `secrets/credentials.json`.
2) Install dependencies:
```bash
uv sync
```
3) Set your OpenAI key:
```bash
export OPENAI_API_KEY="your_key_here"
```
4) Optional: if you want delivery recipients to come from Buttondown first, set:
```bash
export BUTTONDOWN_API_KEY="your_buttondown_api_key_here"
```
5) Review and edit `config.yaml`.

## Run
Production default:

```bash
uv run python daily_pipeline.py
```

Manual debug entrypoints:

```bash
uv run python fetch_gmail.py
uv run python fetch_sources.py
uv run python deliver_digest.py
```

For an end-to-end delivery dry run that sends only to one test inbox:

```bash
uv run python deliver_digest.py --dry-run-recipient you@example.com
```

`main.py` is kept as a compatibility wrapper for the delivery path.

First Gmail-authenticated run will open a browser for Google OAuth and create `secrets/token.json`.

If you change Gmail scopes later, delete `secrets/token.json` and re-run to re-auth.

## Deploy On A Server
Use this when hosting the curator on a server. The intended production flow is:
- a long-running admin server for config and preview
- one daily `daily_pipeline.py` cron run

### One-Time Bootstrap
The repo includes a one-shot bootstrap script that generates:
- a locked-down env file used by all jobs
- wrapper scripts for the admin server, the single daily job, and the manual debug jobs
- a `systemd --user` service for the admin server
- a cron file for the single daily orchestrator schedule

Run once on the server:
```bash
cd /root/newsletter_curator
uv sync
OPENAI_API_KEY='your_key' uv run python scripts/bootstrap_server.py \
  --repo-dir /root/newsletter_curator \
  --admin-host 0.0.0.0 \
  --admin-port 8080 \
  --public-base-url 'https://curator.example.com' \
  --admin-token 'choose-a-long-random-token' \
  --buttondown-api-key 'your_buttondown_api_key' \
  --enable-telemetry \
  --enable-linger \
  --install-crontab
```

What this writes by default:
- `deploy/generated/newsletter-curator.env`
- `deploy/generated/start_admin_server.sh`
- `deploy/generated/run_daily_pipeline.sh`
- `deploy/generated/run_fetch_gmail.sh`
- `deploy/generated/run_fetch_sources.sh`
- `deploy/generated/run_deliver_digest.sh`
- `deploy/generated/newsletter_curator.cron`
- `deploy/generated/newsletter-curator-admin.service`

What the script installs when flags are passed:
- `--install-systemd-user`: copies the generated admin service into `~/.config/systemd/user/`, reloads `systemd --user`, and enables it immediately
- rerunning the bootstrap is safe: it regenerates assets, reloads the user unit, and restarts the admin service so wrapper/env updates are picked up
- `--install-crontab`: installs the generated cron file as the current user’s crontab
- `--enable-linger`: runs `loginctl enable-linger $USER` so the `systemd --user` admin service survives SSH logout

Notes:
- The bootstrap does not start the admin app unless you explicitly pass `--install-systemd-user`.
- The script reads `OPENAI_API_KEY` from the current environment if `--openai-api-key` is not passed explicitly.
- The script reads `BUTTONDOWN_API_KEY` from the current environment if `--buttondown-api-key` is not passed explicitly.
- Telemetry tracking is now disabled by default. Pass `--enable-telemetry` only when the `/track/*` endpoints are publicly reachable.
- Set `--public-base-url` to the externally reachable admin host for telemetry links and open-tracking pixels when telemetry is enabled.
- The generated env file stores the admin token, OpenAI key, and optional Buttondown key with `0600` permissions, so run the bootstrap as the same server user that will own the service and cron jobs.
- The generated cron schedule defaults to:
  - `30 14 * * *` run `daily_pipeline.py`
- The default cron output now uses fixed UTC times instead of `CRON_TZ`, because some cron daemons ignore `CRON_TZ`.
- `30 14 * * *` corresponds to `6:30 AM PST` exactly. On March 22, 2026 Los Angeles is on PDT, so that same fixed UTC schedule currently lands at `7:30 AM` local.
- Fixed UTC does not automatically follow DST, so update the schedule manually if you want a different winter/summer local time mapping.
- Override schedules with:
  - `--daily-schedule`
  - `--cron-timezone` if your cron daemon reliably supports it and you want timezone-based scheduling

### Server Prerequisites
Before running the bootstrap:
- place Gmail OAuth credentials at `secrets/credentials.json`
- create `secrets/token.json` once with an interactive Gmail-authenticated run if needed
- ensure `uv` is installed and on `PATH`

### Verification
After bootstrap:
```bash
crontab -l
tail -n 200 /root/newsletter_curator/deploy/generated/cron.log
```

If you chose to install the admin service too:
```bash
systemctl --user status newsletter-curator-admin
```

For a one-off server-side dry run through the generated wrapper:

```bash
./deploy/generated/run_deliver_digest.sh --dry-run-recipient you@example.com
```

Open the admin UI:
```text
http://YOUR_SERVER:8080/?token=YOUR_ADMIN_TOKEN
```

### Dry-Run Asset Generation
If you want to inspect the generated assets before installing anything:
```bash
cd /root/newsletter_curator
OPENAI_API_KEY='your_key' uv run python scripts/bootstrap_server.py \
  --repo-dir /root/newsletter_curator \
  --output-dir /root/newsletter_curator/deploy/generated-preview \
  --admin-host 0.0.0.0 \
  --admin-port 8080 \
  --admin-token 'choose-a-long-random-token'
```

This generates all deploy files without touching `systemd` or `crontab`.

## Web Config UI
Run a local admin UI to edit `config.yaml`:

```bash
uv run python admin_app.py
```

Default URL is `http://127.0.0.1:8080`.

Optional security token:
- Set `CURATOR_ADMIN_TOKEN` on the server.
- Access with `?token=...` or header `X-Admin-Token: ...`.

Optional Buttondown recipient sync:
- Set `BUTTONDOWN_API_KEY` on the server.
- Delivery will fetch active subscribers from Buttondown first and fall back to `email.digest_recipients` if the API key is missing, the API request fails, or Buttondown returns no deliverable subscribers.

Optional host/port overrides:
- `CURATOR_ADMIN_HOST` (default `127.0.0.1`)
- `CURATOR_ADMIN_PORT` (default `8080`)
- `CURATOR_ADMIN_ENABLE_PREVIEW=1` enables live `/preview` generation. By default the admin app runs in lightweight debug mode and only serves read-only repository views plus any already-stored newsletter for today.
- `CURATOR_ADMIN_RERENDER_STORED_NEWSLETTERS=1` is now only a legacy fallback for stored newsletters that do not have cached `render_groups`. When `render_groups` exist, cached admin previews render from stored content automatically.

Local screenshot review pack for a stored newsletter:
```bash
uv run python scripts/render_preview_review_pack.py \
  --config-path config.yaml \
  --newsletter-date 2026-03-25
```

This is a macOS-only inspection helper that uses Quick Look (`qlmanage`) to write HTML fixtures plus PNG screenshots into a temp or explicit output directory.

## Configuration
Edit `config.yaml`:
- `gmail.label` (default `Newsletters`)
- `gmail.query_time_window` (default `newer_than:1d`)
- `database.path` (default `data/newsletter_curator.sqlite3`)
- `persona.text`
- `development.use_canned_sources`
- `development.canned_sources_file`
- `development.fake_inference`
- `additional_sources.enabled` (default `true` in current checked-in config)
- `additional_sources.script_path` (default `skills/daily-news-curator/scripts/build_daily_digest.py`)
- `additional_sources.feeds_file` (optional custom feed list for the source script)
- `additional_sources.hours`, `additional_sources.top_per_category`, `additional_sources.max_total`
- `limits.max_links_per_email`
- `limits.select_top_stories`
- `limits.max_per_category`
- `limits.final_top_stories` (default `15`)
- `limits.source_quotas` (default `gmail: 10`, `additional_source: 5`)
- `limits.max_article_chars`
- `limits.max_summary_workers`
- `openai.reasoning_model` (default `gpt-5-mini`)
- `openai.summary_model` (default `gpt-5-mini`)
- `tracking.enabled` (default `false`)
- `tracking.base_url` (optional; falls back to `CURATOR_PUBLIC_BASE_URL` or the admin host and port)
- `email.digest_recipients` and `email.alert_recipient`

### Persona Behavior
`persona.text` is used in three distinct places:
- ingest scoring decides which fetched articles are worth an expensive stored summary
- delivery ranking chooses which stored stories make the final newsletter
- summary generation shapes the `Why this matters to me` framing for each stored article summary

In practice, this means the same persona can change both what gets summarized during ingest and what ultimately gets selected for delivery or preview later.

You can override the config file path with `NEWSLETTER_CONFIG`.

## Model Pricing
As of March 21, 2026, the repo default is `gpt-5-mini` for both reasoning and summary work. This switch replaces the older `gpt-4o-mini` reasoning default with the latest low-cost GPT-5 mini tier while keeping the summary model unchanged.

Per 1M text tokens:

| Use | Before model | Before input | Before output | After model | After input | After output |
| --- | --- | --- | --- | --- | --- | --- |
| Reasoning / ranking | `gpt-4o-mini` | $0.15 | $0.60 | `gpt-5-mini` | $0.25 | $2.00 |
| Summary | `gpt-5-mini` | $0.25 | $2.00 | `gpt-5-mini` | $0.25 | $2.00 |

Notes:
- The pricing change only affects the reasoning path because the summary path was already on `gpt-5-mini`.
- Legacy configs that still pin `gpt-4o-mini` for `openai.reasoning_model` are upgraded to `gpt-5-mini` at load time unless you explicitly choose a different non-legacy model.
- Pricing sources:
  - OpenAI API pricing: https://openai.com/api/pricing/
  - GPT-5 model docs: https://platform.openai.com/docs/models/gpt-5/

## Notes
- Article fetching requires outbound network access during ingest jobs, not during delivery.
- Token usage stats are printed per model at the end of each delivery run.
- Source quotas are enforced during final story selection; if one source has fewer usable stored stories, fallback draws from next-ranked candidates.
- Failure alerts are emailed when a job raises an exception.
