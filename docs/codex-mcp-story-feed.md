# Codex MCP Story Feed

This repo publishes a local Codex plugin at `plugins/newsletter-curator-story-feed` and a matching marketplace entry at `.agents/plugins/marketplace.json`.

Use the repo skill `$codex-mcp-story-feed` when Codex should inspect stories already stored in SQLite instead of fetching new content.

Typical Codex prompt:

```text
Use $codex-mcp-story-feed to show the latest stored stories from the repository.
```

Deterministic local helper:

```bash
uv run python skills/codex-mcp-story-feed/scripts/query_story_feed.py --hours 24
uv run python skills/codex-mcp-story-feed/scripts/query_story_feed.py --hours 1 --source-type gmail
uv run python skills/codex-mcp-story-feed/scripts/query_story_feed.py --config-path config.yaml
```

The helper script reads `plugins/newsletter-curator-story-feed/.mcp.json`, launches the published MCP server through that manifest, negotiates `initialize`, and calls `list_recent_stories`.
