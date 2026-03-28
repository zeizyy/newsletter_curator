# Sprint Contract: T57 Admin Service Orchestration

## Objective
Update the deployment bootstrap so the daily pipeline stops the admin app service before running and restarts it afterward to free RAM on the server.

## Scope
- Update `scripts/bootstrap_server.py` so the generated `run_daily_pipeline.sh` wrapper stops the configured `systemd --user` admin service before running `daily_pipeline.py`.
- Ensure the wrapper restarts the admin service on success, failure, and shell interruption by using trap cleanup that covers `EXIT`, `INT`, and `TERM`.
- Treat an already-stopped admin service as non-fatal: the wrapper should still run the pipeline and still attempt the restart cleanup path.
- Keep `daily_pipeline.py` and the admin app code unchanged otherwise.
- Preserve existing bootstrap behavior for admin-service install and cron generation.

## Acceptance Criteria
- The generated `run_daily_pipeline.sh` stops the configured admin service before the pipeline starts.
- The generated wrapper restarts the service even when the pipeline exits non-zero.
- The wrapper preserves the pipeline exit code.
- If the service is already stopped or `systemctl stop` returns non-zero, the wrapper still runs the pipeline and still attempts restart.
- Existing bootstrap or deployment asset behavior still passes.

## Test Coverage
- Extend `tests/integration/test_deployment_bootstrap_assets.py` to execute the generated wrapper with fake `systemctl` and `uv` binaries on `PATH`.
- Assert call order on success: stop admin service, run pipeline, start admin service.
- Add a failure-path assertion that restart still runs when the pipeline fails and that the wrapper returns the pipeline exit code.
- Add an already-stopped-path assertion that a non-zero stop still allows pipeline execution and still triggers restart.
- Static-assert the generated wrapper includes trap cleanup for `EXIT`, `INT`, and `TERM`.

## Test Command
`uv run pytest tests/integration/test_deployment_bootstrap_assets.py -q`

## Evaluator Fail Conditions
- Stop/start logic lives inside `daily_pipeline.py` instead of the generated wrapper.
- Restart only happens on success.
- The wrapper loses the pipeline exit status.
- A non-zero stop prevents the pipeline from running.
- Existing install or bootstrap asset behavior regresses.

## Evaluation
- Status: PASS
- Date: 2026-03-28
- Evidence:
  - `uv run pytest tests/integration/test_deployment_bootstrap_assets.py -q`
  - Evaluator review confirmed the generated wrapper keeps the logic in `scripts/bootstrap_server.py`, preserves the pipeline exit code, and covers success, pipeline-failure, and stop-failure paths.
- Residual Risk:
  - Signal-interruption cleanup is statically asserted in the generated wrapper tests rather than exercised with a live `SIGINT` or `SIGTERM`.
