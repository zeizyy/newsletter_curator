# Sprint Contract: T75 Add a Manual Weekly Digest Override

## Objective
Add an operator option to the generated daily pipeline wrapper so a weekly digest can be triggered manually for the past seven days, independent of the normal weekday schedule.

## Scope
- Add a `daily_pipeline.py` CLI option for manual weekly digest runs.
- Thread that option through `main.run_job()` and delivery scheduling without changing default cron behavior.
- Update the generated `run_daily_pipeline.sh` wrapper so `--weekly-digest` bypasses the Sunday no-op gate and reaches `daily_pipeline.py`.
- Document the manual command.
- Add integration coverage for the CLI override, generated wrapper forwarding, and weekly scheduling semantics.

## Files Likely Touched
- `daily_pipeline.py`
- `main.py`
- `curator/jobs.py`
- `scripts/bootstrap_server.py`
- `README.md`
- `tests/integration/test_daily_pipeline_dry_run_recipient.py`
- `tests/integration/test_deployment_bootstrap_assets.py`
- `tests/integration/test_weekend_delivery_schedule.py`

## Acceptance Criteria
- `run_daily_pipeline.sh --weekly-digest` invokes `daily_pipeline.py --weekly-digest` even on Sunday.
- `daily_pipeline.py --weekly-digest` forces weekly delivery settings, including the seven-day window and weekly subject.
- Default `run_daily_pipeline.sh` invocation still skips on Sunday and follows normal Monday-Friday daily / Saturday weekly behavior.
- Existing dry-run recipient behavior still works with and without the weekly override.

## Test Coverage
- Extend `tests/integration/test_daily_pipeline_dry_run_recipient.py` for CLI override threading.
- Extend `tests/integration/test_deployment_bootstrap_assets.py` for wrapper forwarding on Sunday.
- Extend or reuse weekend schedule coverage to prove a manual weekly override works outside Saturday.

## Test Command
`uv run pytest tests/integration/test_deployment_bootstrap_assets.py tests/integration/test_weekend_delivery_schedule.py tests/integration/test_daily_pipeline_dry_run_recipient.py -q`

## Evaluator Note
A separate evaluator subagent is currently unavailable because the account hit its usage limit. This sprint uses a local contract review plus the listed regression tests.

## Done When
- Operators can manually run a weekly digest from the generated wrapper.
- Default scheduled behavior is unchanged.
- The manual override is documented and tested.
