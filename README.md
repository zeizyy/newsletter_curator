# Newsletter Curator

Personal newsletter curator that combines Gmail newsletter links with RSS-based source recall, ranks candidates with an LLM, summarizes selected articles, and emails a digest via Gmail API.

## Features
- Gmail API ingestion for label `Newsletters` and `newer_than:1d`
- Hybrid ingestion from RSS via `skills/daily-news-curator` (configurable on/off)
- HTML link extraction with heuristics to skip non-article URLs
- Two-stage LLM flow: select top stories, then summarize articles
- Final selection quotas by source type (default: `gmail=10`, `additional_source=5`)
- Automatic backfill when article fetch/summary fails (uses next-ranked candidates)
- Compact pipeline metrics and token usage logging (no story-level terminal flood)
- Sends final digest via Gmail API

## Pipeline Design
1) Retrieve candidate links from Gmail newsletters.
2) Retrieve additional candidates from RSS/feeds via `skills/daily-news-curator/scripts/build_daily_digest.py` (`--output json`).
3) Merge Gmail + additional-source candidates and dedupe by URL.
4) Rank candidates with `openai.reasoning_model`.
5) Apply category cap + source quotas in post-processing.
6) Fetch and summarize selected stories with `openai.summary_model`.
7) If a selected story cannot be fetched/summarized, skip it and backfill from next-ranked candidates.
8) Render plain text + HTML digest and send to configured recipients.

Runtime output includes:
- `messages_retrieved`
- `links_retrieved` (gmail vs additional_sources)
- `links_merged_deduped`
- ranked/final counts sliced by source type and source name
- summary completion/backfill/skip counts
- per-model token usage

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
```bash
uv run python main.py
```

First run will open a browser for Google OAuth and create `secrets/token.json`.

If you change Gmail scopes later, delete `secrets/token.json` and re-run to re-auth.

## Configuration
Edit `config.yaml`:
- `gmail.label` (default `Newsletters`)
- `gmail.query_time_window` (default `newer_than:1d`)
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
- Article fetching requires outbound network access.
- Token usage stats are printed per model at the end of each run.
- Source quotas are enforced during final story selection; if one source has fewer fetchable stories, fallback draws from next-ranked candidates.
- Failure alerts are emailed when the job raises an exception.
