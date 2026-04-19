# Sprint Contract: T73 Skip the Whole Daily Pipeline on Sunday

## Objective
Make the generated `run_daily_pipeline.sh` wrapper exit successfully on Sundays without invoking the daily pipeline, so the cron job becomes a no-op for that day.

## Scope
- Update `scripts/bootstrap_server.py` so the generated `run_daily_pipeline.sh` performs a Sunday check before any admin-service pause logic or pipeline invocation.
- On Sunday, exit 0 without calling `daily_pipeline.py`, `scripts/send_pipeline_failure_alert.py`, or `systemctl`.
- Leave the existing Monday-Saturday behavior unchanged.
- Do not change the delivery scheduler in `curator/jobs.py` in this sprint; this task is wrapper-level only.

## Files Likely Touched
- `scripts/bootstrap_server.py`
- `tests/integration/test_deployment_bootstrap_assets.py`
- `README.md` only if the generated-wrapper behavior needs a documentation note

## Acceptance Criteria
- The generated `run_daily_pipeline.sh` returns exit code 0 on Sunday and skips the rest of the script.
- On Sunday, the wrapper does not stop or start the admin service.
- On Sunday, the wrapper does not invoke `daily_pipeline.py`.
- On Sunday, the wrapper does not send a failure alert.
- On non-Sunday runs, the wrapper keeps the current stop / run / alert / restart behavior.
- Existing deployment-asset generation remains valid.

## Test Coverage
- Extend `tests/integration/test_deployment_bootstrap_assets.py`.
- Add a Sunday-path test that runs the generated wrapper with a stubbed weekday source, plus fake `systemctl` and `uv` binaries on `PATH`.
- Assert the Sunday path never includes `systemctl`, `uv run python daily_pipeline.py`, or the alert script.
- Keep the existing wrapper regression tests for success, failure, and stop-failure paths passing.

## Test Command
`uv run pytest tests/integration/test_deployment_bootstrap_assets.py -q`

## Evaluator Verdict
Pre-implementation contract review: PASS. The sprint contract is specific and testable; it locks the change to the generated wrapper, defines the Sunday short-circuit behavior at the wrapper boundary, excludes `curator/jobs.py`, and names the exact integration test file and pytest command.

## Evaluator Fail Conditions
- The wrapper still launches `daily_pipeline.py` on Sunday.
- The wrapper stops or restarts the admin service on Sunday.
- The wrapper sends a failure alert for the Sunday skip path.
- Non-Sunday behavior regresses.
- The change is made in `curator/jobs.py` instead of the generated wrapper.

## Dependencies / Risks
- Dependency: the follow-up Pacific-time task (`T74`) will pin the weekday source, so this sprint keeps the Sunday gate implementation small and testable.
- Risk: this sprint may use server-local time structurally until `T74` makes the weekday source explicitly Pacific.

## Done When
- The generated wrapper no-ops on Sunday.
- The Sunday regression test passes.
- Existing deployment bootstrap tests still pass.
- The repository remains mergeable and ready for the Pacific-time follow-up.
