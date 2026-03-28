# Sprint Contract: T64 MCP Launch Docs And Smoke

## Objective
Document the checked-in MCP launch path and add a small smoke test that proves the entrypoint is usable without re-testing the full story-feed contract.

## Scope
- Add a thin argparse-based CLI wrapper to `scripts/newsletter_mcp_server.py`.
- Support built-in `--help` plus an optional `--config-path` argument for selecting the config file used by the server.
- Keep the MCP server behavior unchanged aside from the launch wrapper: same stdio transport, same read-only semantics, same one-tool surface, same response schema.
- Document the exact launch command and config assumptions in `README.md`.
- Add one focused smoke test file that checks `--help` output and a minimal `initialize` handshake using the checked-in script.

## Test Coverage
- `tests/integration/test_mcp_story_feed_help.py`

## Test Command
`uv run pytest tests/integration/test_mcp_story_feed_help.py -q`

## Evaluator Fail Conditions
- The README launch instructions do not match the checked-in script behavior.
- The script lacks a discoverable local help path.
- The smoke test reopens full story-feed semantics instead of staying focused on the entrypoint.
- The task changes payload shape, tool arguments, transport behavior, or other T63/T65 concerns.

## Done When
- The README documents a concrete operator launch path for the read-only MCP server.
- `uv run python scripts/newsletter_mcp_server.py --help` is informative and stable.
- The smoke test proves the entrypoint is callable and can answer `initialize` offline.

## Evaluation
- Status: PASS
- Date: 2026-03-28
- Evidence:
  - `uv run pytest tests/integration/test_mcp_story_feed_help.py -q`
  - `uv run pytest tests/integration/test_mcp_recent_story_feed_server.py -q`
  - `git diff --check`
  - Manual review of `README.md`, `scripts/newsletter_mcp_server.py`, `curator/mcp_server.py`, `agent_contracts/T64_mcp_launch_docs_and_smoke.md`, and `tests/integration/test_mcp_story_feed_help.py`
- Outcome:
  - The sprint adds a concrete, documented launch path for the read-only MCP server without changing story-feed behavior.
  - `scripts/newsletter_mcp_server.py` now has a discoverable help surface and optional `--config-path` support.
  - The smoke test proves the entrypoint is callable locally and can negotiate `initialize` offline while staying out of the full `list_recent_stories` contract.
- Residual Risk:
  - This sprint does not re-test `tools/list` or `tools/call`; that remains covered by `T63`.
