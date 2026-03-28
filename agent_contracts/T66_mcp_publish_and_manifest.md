# Sprint Contract: T66 MCP Publish And Manifest

## Objective
Publish the read-only MCP server as a repo-local Codex-discoverable plugin without changing server semantics.

## Scope
- Add a repo-local plugin at `plugins/newsletter-curator-story-feed`.
- Fill in `.codex-plugin/plugin.json` with real metadata for the read-only story-feed plugin.
- Add `.mcp.json` that launches the checked-in MCP server through the existing repo script.
- Add or update `.agents/plugins/marketplace.json` so the plugin is discoverable as a local marketplace entry.
- Document the repo-local plugin location and publish path in `README.md`.
- Keep publishing separate from Codex workflow docs and from server behavior changes.

## Test Coverage
- `tests/integration/test_mcp_publish_manifest.py`

## Test Command
`uv run pytest tests/integration/test_mcp_publish_manifest.py -q`

## Evaluator Fail Conditions
- The manifest does not point at the checked-in MCP launch path.
- The marketplace entry is missing required policy fields or an incorrect plugin path.
- The publish step changes MCP tool semantics, transport behavior, or response shape.
- The smoke test does not prove the published manifest can start the server locally.

## Done When
- The repo-local plugin manifest and marketplace entry are complete enough for Codex discovery.
- The README documents where the published plugin lives and how it launches the MCP server.
- The manifest smoke test passes offline.

## Evaluation
- Status: PASS
- Date: 2026-03-28
- Evidence:
  - `uv run pytest tests/integration/test_mcp_publish_manifest.py -q`
  - `uv run pytest tests/integration/test_mcp_recent_story_feed_server.py tests/integration/test_mcp_story_feed_help.py -q`
  - `git diff --check`
  - Manual review of `plugins/newsletter-curator-story-feed/.codex-plugin/plugin.json`, `plugins/newsletter-curator-story-feed/.mcp.json`, `.agents/plugins/marketplace.json`, `README.md`, `agent_contracts/T66_mcp_publish_and_manifest.md`, and `tests/integration/test_mcp_publish_manifest.py`
- Outcome:
  - The repo-local plugin manifest and marketplace entry are sufficient for Codex discovery of the read-only MCP server.
  - The published `.mcp.json` points at the checked-in launch script and preserves the existing story-feed server behavior.
  - The manifest smoke test proves the published plugin can start the MCP server locally and negotiate `initialize` offline.
- Residual Risk:
  - This is a repo-local publish surface, so if the eventual Codex environment expects a different global plugin distribution path, that separate installation workflow still needs validation in `T67`.
