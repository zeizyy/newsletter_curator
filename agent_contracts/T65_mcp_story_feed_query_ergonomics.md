# Sprint Contract: T65 MCP Story Feed Query Ergonomics

## Objective
Add bounded query ergonomics to `list_recent_stories` without changing publishing, packaging, or agent integration.

## Scope
- Extend `list_recent_stories` with optional `hours` and `source_type` arguments only.
- Bound `hours` to integer values from `1` through `168`, with the default remaining `24`.
- Treat `source_type` as an optional exact-match filter over stored repository source types.
- Keep the server read-only, metadata-only, and newline-delimited JSON-RPC over stdio.
- Preserve the default response shape and default no-argument behavior.
- Reject invalid arguments through MCP-visible tool errors without mutating the repository.
- Do not add README publish docs, plugin manifests, Codex workflow artifacts, or other client-integration files in this sprint.

## Test Coverage
- Update `tests/integration/test_mcp_recent_story_feed_server.py` to cover:
- the unchanged default path,
- a filtered `hours=1` call,
- a filtered `source_type='gmail'` call,
- and one invalid-arguments error path.

## Test Command
`uv run pytest tests/integration/test_mcp_recent_story_feed_server.py -q`

## Evaluator Fail Conditions
- Default behavior changes when no arguments are passed.
- The task introduces publish or agent-integration artifacts.
- The tool accepts unbounded or ambiguous query arguments.
- Any live retrieval, summarization, or repository mutation path is introduced.

## Done When
- `list_recent_stories` supports the bounded ergonomic arguments.
- The default 24-hour read-only feed still works unchanged.
- The integration test passes offline.

## Evaluation
- Status: PASS
- Date: 2026-03-28
- Evidence:
  - `uv run pytest tests/integration/test_mcp_recent_story_feed_server.py -q`
  - `uv run pytest tests/integration/test_mcp_story_feed_help.py -q`
  - `git diff --check`
  - Manual review of `agent_spec.md`, `agent_tasks.json`, `agent_contracts/T65_mcp_story_feed_query_ergonomics.md`, `curator/story_feed.py`, `curator/mcp_server.py`, and `tests/integration/test_mcp_recent_story_feed_server.py`
- Outcome:
  - `list_recent_stories` now supports bounded query ergonomics for `hours` and `source_type` without changing the default read-only 24-hour feed.
  - Invalid arguments fail cleanly with MCP-visible tool errors.
  - The integration test covers the default path, filtered paths, and the invalid-arguments path offline.
- Residual Risk:
  - The broader publish and Codex-consumption work is still queued as follow-on tasks, so those workflows remain unimplemented for now.
