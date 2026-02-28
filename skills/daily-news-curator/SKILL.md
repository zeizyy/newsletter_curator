---
name: daily-news-curator
description: Build a daily news digest from direct publisher feeds (RSS/Atom) with focus on AI, markets, and top general news. Use when asked to gather latest headlines, rank stories by category, summarize multi-source news, or replace Gmail-based newsletter ingestion with source-based ingestion.
---

# Daily News Curator

## Overview

Use this skill to fetch fresh headlines directly from source feeds, deduplicate, rank by priority, and produce a concise daily digest.

## Workflow

1. Confirm scope:
- Use categories `ai`, `markets`, and `top-news` by default.
- Confirm recency window (default `24h`) and output format (`markdown` by default).
- Confirm source overrides if the user names specific publishers.

2. Choose feed sources:
- Start from `references/default_feeds.md`.
- Keep at least 2 sources per category when possible.
- Prefer official publisher RSS endpoints over unofficial mirrors.

3. Fetch and normalize:
- Run `scripts/build_daily_digest.py` to fetch RSS/Atom feeds, normalize item fields, and deduplicate by canonical URL.
- Keep failures isolated per feed and continue processing healthy sources.

4. Rank and select:
- Apply category quotas and recency-first sorting.
- Then apply the priority order in `references/ranking_criteria.md`.

5. Deliver digest:
- Return sectioned output with:
  - headline
  - source
  - published timestamp
  - URL
  - one-line why-it-matters summary
- If requested, produce both Markdown and JSON.

## Run Script

Run from inside this skill directory:

```bash
python scripts/build_daily_digest.py --output markdown
```

Useful options:
- `--hours 24`: time window for freshness
- `--top-per-category 5`: per-category cap
- `--max-total 20`: total digest size
- `--output markdown|json`
- `--feeds-file /path/to/feeds.json`: custom sources

## Quality Bar

- Do not include stale stories outside the requested recency window.
- Do not include duplicate stories across feeds unless links differ materially.
- Keep category balance so one category does not dominate the digest.
- Always keep source attribution with direct links.

## Resources

- `scripts/build_daily_digest.py`: deterministic feed ingestion and digest rendering.
- `references/default_feeds.md`: starter feed list, including CNN and Sherwood.
- `references/ranking_criteria.md`: tie-break and priority guidance for final curation.
