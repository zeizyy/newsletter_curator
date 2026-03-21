# Newsletter Curator

Personal newsletter curator with a repository-first architecture: Gmail newsletters and publisher feeds are ingested into a local SQLite repository, then a separate delivery job ranks, summarizes, and emails the digest from stored snapshots.

## Features
- Separate ingest jobs for Gmail newsletters and additional publisher feeds
- Local SQLite repository for normalized stories, article snapshots, and run history
- Admin UI for source selection and persona text
- Repo-only delivery job with no live Gmail reads or live article fetches at send time
- Two-stage LLM flow: select top stories, then summarize stored article text
- Final selection quotas by source type (default: `gmail=10`, `additional_source=5`)
- Delivery readiness checks against ingest run history and stored fresh stories
- Deterministic canned-data mode for local development and integration testing

## Pipeline Design
1) `fetch_gmail.py` reads Gmail newsletters, extracts candidate links, fetches article text, and writes stories plus snapshots into the repository.
2) `fetch_sources.py` reads additional publisher feeds, fetches article text, and writes stories plus snapshots into the same repository.
3) `deliver_digest.py` reads only repository-backed stories within the configured freshness windows.
4) Delivery merges Gmail + additional-source candidates, dedupes by URL, ranks with `openai.reasoning_model`, applies source quotas, summarizes stored article text with `openai.summary_model`, and emails the digest.
5) Delivery records run metadata and warns when one source type is stale or has a failed latest ingest, but can still proceed if another source type has fresh repository data.

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
4) Review and edit `config.yaml`.

## Run
In production, run the jobs separately:

```bash
uv run python fetch_gmail.py
uv run python fetch_sources.py
uv run python deliver_digest.py
```

`main.py` is kept as a compatibility wrapper for the delivery job.

First Gmail-authenticated run will open a browser for Google OAuth and create `secrets/token.json`.

If you change Gmail scopes later, delete `secrets/token.json` and re-run to re-auth.

## Deploy As Daily Cronjobs (Server)
Use this when hosting the curator on a server. The intended production flow is two ingest jobs plus one delivery job.

1) Prepare runtime once:
```bash
cd /root/newsletter_curator
uv sync
```

2) Ensure required runtime files/env are present:
- `secrets/credentials.json`
- `secrets/token.json` (generate once with an interactive run if needed)
- `OPENAI_API_KEY` available to cron (via shell profile or explicit cron env line)

3) Test manual runs:
```bash
cd /root/newsletter_curator
OPENAI_API_KEY='your_key' uv run python fetch_gmail.py
OPENAI_API_KEY='your_key' uv run python fetch_sources.py
OPENAI_API_KEY='your_key' uv run python deliver_digest.py
```

4) Create cron entries (example timings):
```bash
crontab -e
```
Add:
```cron
15 6 * * * cd /root/newsletter_curator && OPENAI_API_KEY='your_key' /root/.local/bin/uv run python fetch_gmail.py >> /root/newsletter_curator/cron.log 2>&1
25 6 * * * cd /root/newsletter_curator && OPENAI_API_KEY='your_key' /root/.local/bin/uv run python fetch_sources.py >> /root/newsletter_curator/cron.log 2>&1
0 7 * * * cd /root/newsletter_curator && OPENAI_API_KEY='your_key' /root/.local/bin/uv run python deliver_digest.py >> /root/newsletter_curator/cron.log 2>&1
```

5) Verify cron is installed:
```bash
crontab -l
```

6) Check logs after scheduled run:
```bash
tail -n 200 /root/newsletter_curator/cron.log
```

Notes:
- Cron uses the server timezone. Set it explicitly on the server if needed.
- Use absolute paths in cron commands.
- If your API key rotates, update the cron entry or env source accordingly.
- `deliver_digest.py` will fail fast if there is no delivery-ready repository data for any required source type.

## Web Config UI
Run a local admin UI to edit `config.yaml`:

```bash
uv run python admin_app.py
```

Default URL is `http://127.0.0.1:8080`.

Optional security token:
- Set `CURATOR_ADMIN_TOKEN` on the server.
- Access with `?token=...` or header `X-Admin-Token: ...`.

Optional host/port overrides:
- `CURATOR_ADMIN_HOST` (default `127.0.0.1`)
- `CURATOR_ADMIN_PORT` (default `8080`)

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
- `openai.reasoning_model` (default `gpt-4o-mini`)
- `openai.summary_model` (default `gpt-5-mini`)
- `email.digest_recipients` and `email.alert_recipient`

You can override the config file path with `NEWSLETTER_CONFIG`.

## Notes
- Article fetching requires outbound network access during ingest jobs, not during delivery.
- Token usage stats are printed per model at the end of each delivery run.
- Source quotas are enforced during final story selection; if one source has fewer usable stored stories, fallback draws from next-ranked candidates.
- Failure alerts are emailed when a job raises an exception.
