# Newsletter Curator

Personal newsletter curator that reads labeled Gmail newsletters, extracts links, ranks top stories, fetches articles, and produces LLM-written summaries. Outputs to console and emails the digest using Gmail API.

## Features
- Gmail API ingestion for label `Newsletters` and `newer_than:1d`
- HTML link extraction with heuristics to skip non-article URLs
- Two-stage LLM flow: select top stories, then summarize articles
- Parallelized article fetching and summarization
- Sends final digest via Gmail API

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
- `limits.max_links_per_email`
- `limits.top_stories`
- `limits.max_article_chars`
- `limits.max_summary_workers`
- `openai.reasoning_model` (default `gpt-4o-mini`)
- `openai.summary_model` (default `gpt-5-mini`)
- `email.digest_recipients` and `email.alert_recipient`

You can override the config file path with `NEWSLETTER_CONFIG`.

## Notes
- Article fetching requires outbound network access.
- Token usage stats are printed per model at the end of each run.
- Failure alerts are emailed when the job raises an exception.
