---
name: codex-mcp-story-feed
description: Use when Codex should inspect stored Newsletter Curator stories through the published local MCP plugin instead of fetching new content. This skill is for repo-local, read-only story queries, especially when the user wants recent repository stories, source filtering, or a deterministic JSON snapshot from the MCP feed.
---

# Codex MCP Story Feed

## Overview

Use the published local MCP plugin `newsletter-curator-story-feed` to inspect stories already stored in the repository database. This skill keeps the workflow read-only and avoids fresh retrieval or summarization.

## When To Use It

- The user wants recent stories already stored in SQLite.
- The user wants a read-only snapshot by `hours` or `source_type`.
- You need deterministic JSON output for downstream reasoning or debugging.
- The task should go through the published plugin path rather than calling repository code directly.

## Workflow

1. Confirm the local plugin exists at `plugins/newsletter-curator-story-feed` and the marketplace entry exists at `.agents/plugins/marketplace.json`.
2. Prefer the helper script when you want a deterministic local result from the published plugin path:

```bash
uv run python skills/codex-mcp-story-feed/scripts/query_story_feed.py --hours 24
```

3. Add `--source-type gmail` or another repository source type when the request is source-specific.
4. Pass `--config-path <path>` when the repo should use a non-default config or test database.
5. Treat the result as read-only stored metadata. Do not turn this workflow into fetch, summarize, or mutate steps.

## Codex Usage

- In Codex, explicit prompts should mention `$codex-mcp-story-feed`.
- Example prompts:
  - `Use $codex-mcp-story-feed to show the latest stored stories.`
  - `Use $codex-mcp-story-feed to inspect Gmail stories from the last hour.`
  - `Use $codex-mcp-story-feed and return the JSON payload for recent repository stories.`

## Script Notes

- The helper script reads the published plugin manifest at `plugins/newsletter-curator-story-feed/.mcp.json`.
- It launches the MCP server through that manifest, performs `initialize`, then calls `list_recent_stories`.
- It is a deterministic fallback when you want the published Codex plugin path exercised directly.
