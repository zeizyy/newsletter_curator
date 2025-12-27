# Newsletter Curator Plan

## 1) Requirements & outputs
- Confirm Gmail label name for newsletters (case-sensitive) and timezone for “past 24 hours.”
- Define output format: e.g., morning digest with 2–5 “top stories,” each with title, source, summary, why-it-matters, and links.
- Decide delivery channel (console, email to self, Notion, Slack, etc.) and retention (store past digests?).

Decisions:
- Run locally for now.
- Gmail label: `Newsletters`.
- Output: console text for quick testing; later switch to email.
- No cap on the number of links+contexts sent to the LLM initially.

## 2) Gmail API setup
- Use existing Google Cloud project and enable Gmail API.
- Configure OAuth consent screen; use Desktop app for local runs.
- Generate OAuth credentials and plan token storage (local file, encrypted store).
- Validate scopes needed (read-only is enough) and token refresh behavior.

Decisions:
- Existing OAuth credentials available.
- OAuth app type: Desktop.
- Credentials file stored at `secrets/credentials.json` (gitignored).
- Token cache stored at `secrets/token.json` (gitignored).

## 3) Email ingestion
- Query Gmail: label + `newer_than:1d` or explicit `after:` timestamp.
- Fetch message metadata and bodies; parse MIME for text/plain and text/html.
- Normalize text (strip signatures/footers if feasible) and keep minimal fields (sender, subject, date).

## 4) Link/context extraction
- Parse HTML to extract links with anchor text.
- For each link, capture surrounding text snippet (e.g., 1–2 sentences).
- De-duplicate links across newsletters and canonicalize URLs (strip tracking params).

## 5) LLM synthesis & ranking
- Define a prompt schema: input = list of links + anchor/context + source; output = ranked stories.
- Encode interest priority: Markets/stocks/macro > Tech company news & strategy > AI/ML industry > Tech blogs > Interesting datapoints.
- Add guardrails: max stories, avoid duplicates, prefer authoritative sources.
- Choose model/provider, set token budget and cost controls.

## 6) Orchestration & scheduling
- Decide runtime: local cron, server, or GitHub Actions.
- Logging: store last run timestamp, counts, failures.
- Idempotency: track processed message IDs to avoid reprocessing.

## 7) Testing & validation
- Dry-run with a small batch of messages.
- Validate extraction quality and LLM output vs. your interest priorities.
- Add a feedback loop: mark stories as useful to tune prompts or ranking.

## Deployment (DigitalOcean)
- Create a Basic Droplet (Ubuntu 22.04) and add your SSH key.
- SSH in and install dependencies: `git`, `uv`, Python 3.13.
- Clone repo to the Droplet and copy `secrets/credentials.json`.
- Set `OPENAI_API_KEY` (and optional model env vars) via shell profile or `.env`.
- Run `uv run python main.py` once to generate `secrets/token.json` (OAuth).
- Create a daily cron entry to run the script at your preferred time.
- Redirect output to a log file and set up simple log rotation.
- Optional: add a failure email/notification or heartbeat ping.

## Progress log
- Implemented Gmail Desktop OAuth, message fetching, and HTML link extraction in `main.py`.
- Added OpenAI-based LLM summarization for ranked digest output (plain text).
- Added two-stage LLM flow: select top stories then summarize fetched articles with key takeaways and why it matters.
- Added Gmail API send to email the final digest to `zeizyy@gmail.com`.
- Added `config.yaml` and refactored runtime settings to load from config.
- Added failure alert emails on exceptions.

## Next: Failure alerts + Config
Decisions:
- Use `config.yaml` for configuration.
- Failure alerts go to `zeizyy@gmail.com`.
