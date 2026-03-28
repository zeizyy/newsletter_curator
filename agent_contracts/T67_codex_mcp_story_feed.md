# Sprint Contract: T67 Codex MCP Story Feed Workflow

## Objective
Add a Codex-oriented workflow that uses the published MCP story-feed plugin rather than raw repository calls.

## Scope
- Add a repo skill at `skills/codex-mcp-story-feed`.
- Add a helper script that reads the published plugin manifest, starts the MCP server through that manifest, and calls `list_recent_stories`.
- Add a short operator or developer doc for using the skill and helper from Codex.
- Keep the workflow read-only and separate from plugin publishing plus server implementation.

## Test Coverage
- `tests/integration/test_codex_mcp_story_feed_smoke.py`

## Test Command
`uv run pytest tests/integration/test_codex_mcp_story_feed_smoke.py -q`

## Evaluator Fail Conditions
- The skill does not clearly describe when to use the Codex MCP workflow.
- The helper bypasses the published plugin manifest instead of using it.
- The workflow changes MCP server behavior instead of consuming the existing published surface.
- The smoke test does not prove the helper can call `list_recent_stories` offline.

## Done When
- Codex has a repo skill and doc for the story-feed MCP workflow.
- The helper script can query the published MCP plugin and print JSON.
- The workflow smoke test passes offline.

## Evaluation
- Status: PASS
- Evidence:
  - Added `skills/codex-mcp-story-feed/SKILL.md` plus `skills/codex-mcp-story-feed/agents/openai.yaml` so Codex has a concrete repo-local workflow prompt and usage guidance.
  - Added `skills/codex-mcp-story-feed/scripts/query_story_feed.py`, which reads `plugins/newsletter-curator-story-feed/.mcp.json`, launches the published stdio server, negotiates `initialize`, and calls `list_recent_stories` without bypassing the manifest.
  - Added `docs/codex-mcp-story-feed.md` for operator and developer usage of the skill and deterministic helper.
  - `uv run pytest tests/integration/test_codex_mcp_story_feed_smoke.py -q` passed, proving the helper can query the published MCP plugin offline against a seeded temporary SQLite repository.
  - `uv run pytest tests/integration/test_mcp_publish_manifest.py tests/integration/test_mcp_recent_story_feed_server.py tests/integration/test_mcp_story_feed_help.py -q` passed, confirming the existing publish path and server behavior stayed intact.
