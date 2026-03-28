# Sprint Contract: T63 Recent Story Feed MCP Server

## Objective
Expose the existing repository stories from the last 24 hours through a minimal, read-only MCP server over stdio.

## Scope
- Implement newline-delimited JSON-RPC over stdio, matching the current MCP stdio transport.
- Ship the checked-in launch path as `uv run python scripts/newsletter_mcp_server.py`.
- Support exactly these request methods in the first slice: `initialize`, `tools/list`, `tools/call`, and `ping`.
- Expose exactly one tool named `list_recent_stories`.
- Keep the tool input schema as an empty object for now.
- Query the existing SQLite database in read-only mode and do not call repository initialization or schema reset paths.
- Filter and sort stories by `COALESCE(NULLIF(published_at, ''), first_seen_at)`, newest first, with `id DESC` as a deterministic tiebreaker.
- Return structured metadata only. Do not return `article_text`, raw payload blobs, or any live-fetch artifacts.
- Do not trigger fresh retrieval, article fetching, enrichment, or summarization at tool-call time.

## Tool Output Contract
- `structuredContent` is an object with:
- `generated_at`: ISO 8601 UTC string.
- `window_hours`: integer, always `24` in this sprint.
- `story_count`: integer.
- `stories`: array of objects with these fields:
- `id`: integer.
- `story_key`: string.
- `source_type`: string.
- `source_name`: string.
- `subject`: string.
- `url`: string.
- `canonical_url`: string.
- `anchor_text`: string.
- `context`: string.
- `category`: string.
- `published_at`: ISO 8601 string or `null`.
- `first_seen_at`: ISO 8601 string.
- `last_seen_at`: ISO 8601 string.
- `effective_timestamp`: ISO 8601 string used for filtering and sort order.
- `summary`: string.
- `summary_headline`: string.
- `summary_body`: string.
- `article_fetched_at`: ISO 8601 string or `null`.
- `paywall_detected`: boolean.
- `paywall_reason`: string or `null`.
- `summarized_at`: ISO 8601 string or `null`.
- The tool response also includes a single text content block containing the same payload serialized as JSON for clients that only read text content.

## Test Coverage
- `tests/integration/test_mcp_recent_story_feed_server.py`

## Test Command
`uv run pytest tests/integration/test_mcp_recent_story_feed_server.py -q`

## Evaluator Fail Conditions
- The checked-in launch command is ambiguous or does not work.
- The server speaks a transport other than newline-delimited JSON-RPC over stdio.
- `tools/list` exposes more than one tool or fails to mark the tool read-only.
- The response schema is not deterministic about nulls, booleans, or omitted fields.
- Filtering or ordering does not use `COALESCE(NULLIF(published_at, ''), first_seen_at)` with `id DESC` tiebreaking.
- The server creates, initializes, resets, or mutates the SQLite database during a normal call.
- Any live retrieval, article fetching, enrichment, or summarization code path is triggered.

## Done When
- A subprocess client can initialize the server, list tools, and call `list_recent_stories`.
- The returned payload is JSON-serializable, metadata-only, and limited to the last 24 hours.
- The offline integration test passes against a seeded repository whose SQLite file permissions are read-only.

## Evaluation
- Status: PASS
- Date: 2026-03-28
- Evidence:
  - `uv run pytest tests/integration/test_mcp_recent_story_feed_server.py -q`
  - `git diff --check`
  - Manual review of `agent_spec.md`, `agent_tasks.json`, `agent_contracts/T63_recent_story_feed_mcp_server.md`, `curator/story_feed.py`, `curator/mcp_server.py`, `scripts/newsletter_mcp_server.py`, and `tests/integration/test_mcp_recent_story_feed_server.py`
- Outcome:
  - The sprint delivers a read-only stdio MCP server with exactly one `list_recent_stories` tool backed by the existing SQLite repository.
  - The server uses read-only SQLite access, avoids repository initialization/reset paths, and returns metadata-only results for the last 24 hours with deterministic ordering.
  - The subprocess integration test covers `initialize`, `tools/list`, `ping`, and `tools/call`, including stale-story exclusion and inclusion of stories whose `published_at` is blank but `first_seen_at` is recent.
- Residual Risk:
  - The transport is a thin custom newline-delimited JSON-RPC implementation, so if the project later swaps to a different MCP transport stack, client compatibility should be revalidated.
