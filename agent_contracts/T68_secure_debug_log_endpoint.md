# Sprint Contract: T68 Secure Debug Log Endpoint

## Objective
Add a token-gated, read-only Flask endpoint that exposes a bounded tail of one configured debug log file for production troubleshooting.

## Scope
- Persist structured debug events to a configured file without changing the existing stdout log behavior.
- Add `GET /debug/logs` on the admin server.
- Require a dedicated `CURATOR_DEBUG_LOG_TOKEN` on every request.
- Read exactly one configured absolute file path from `CURATOR_DEBUG_LOG_PATH`.
- Support `lines=<int>` with a default of `200` and a hard cap of `500`.
- Return a stable JSON payload with `path`, `line_count`, `truncated`, and `lines`.
- Fail safely for missing token, invalid token, invalid `lines`, and missing or unreadable log configuration.

## Test Coverage
- `tests/integration/test_admin_debug_log_endpoint.py`

## Test Command
`uv run pytest tests/integration/test_admin_debug_log_endpoint.py`

## Evaluator Fail Conditions
- The route reuses admin, subscriber, or MCP auth instead of a dedicated debug token.
- The implementation allows request-time file path selection, relative paths, or symlink traversal.
- The endpoint returns unbounded output or an unstable response shape.
- Missing config or invalid input leaks filesystem details or crashes the server.
- Existing stdout-based observability behavior is removed or broken.

## Done When
- Structured debug events can be mirrored into one configured debug log file.
- `GET /debug/logs` returns a bounded JSON tail from that file only when `CURATOR_DEBUG_LOG_TOKEN` is valid.
- Invalid or missing configuration fails safely and predictably.
- The dedicated debug-log endpoint integration test passes.

## Evaluation
- Status: PASS
- Date: 2026-03-31
- Evidence:
  - `uv run pytest tests/integration/test_admin_debug_log_endpoint.py tests/integration/test_deployment_bootstrap_assets.py tests/integration/test_http_mcp_server.py tests/integration/test_admin_login_flow.py tests/integration/test_offline_e2e_fixture_runner.py -q`
  - Manual review of `admin_app.py`, `curator/debug_logs.py`, `curator/observability.py`, `scripts/bootstrap_server.py`, `README.md`, `tests/integration/test_admin_debug_log_endpoint.py`, and `tests/integration/test_deployment_bootstrap_assets.py`
- Outcome:
  - T68 passes review. The debug endpoint is header-only (`Authorization: Bearer` or `X-Debug-Log-Token`), uses one configured absolute log path with symlink components rejected, does not accept request-time file selection, clamps `lines` to a 500 max, and fails safely for missing config, missing file, and invalid input.
  - Bootstrap and README now surface the dedicated debug token and fixed log path.
  - Stdout observability remains intact while structured events are mirrored to the configured debug log file.
- Residual Risk:
  - The endpoint exposes log content verbatim, so operators should point `CURATOR_DEBUG_LOG_PATH` at the dedicated structured debug log file rather than a broader system log that may contain unrelated sensitive output.
