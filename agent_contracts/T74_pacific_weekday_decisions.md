# Sprint Contract: T74 Verify Weekday Decisions Use Pacific Time

## Objective
Make delivery weekday decisions use `America/Los_Angeles` consistently, so daily, weekly, and Sunday-skip behavior follows Pacific calendar days rather than UTC or server-local time.

## Scope
- Update Python delivery scheduling in `curator/jobs.py` to classify weekdays after converting to Pacific time.
- Keep the generated `run_daily_pipeline.sh` Sunday gate aligned with Pacific time.
- Keep non-scheduling timestamps and story freshness logic unchanged.
- Add regression coverage for UTC boundary cases that fall on the previous Pacific day.

## Files Likely Touched
- `curator/jobs.py`
- `scripts/bootstrap_server.py`
- `tests/integration/test_weekend_delivery_schedule.py`
- `tests/integration/test_deployment_bootstrap_assets.py`

## Acceptance Criteria
- A UTC timestamp that is Sunday in UTC but Saturday in Pacific time is classified as the weekly Saturday issue.
- Newsletter storage date follows the Pacific delivery date for scheduled delivery decisions.
- The generated daily wrapper uses `TZ=America/Los_Angeles` for its Sunday skip check.
- Existing Saturday weekly, Sunday skipped, and non-Sunday wrapper behavior still passes.

## Test Coverage
- Add an integration boundary test in `tests/integration/test_weekend_delivery_schedule.py`.
- Extend deployment bootstrap coverage to verify the generated wrapper invokes `date` with Pacific timezone.

## Test Command
`uv run pytest tests/integration/test_weekend_delivery_schedule.py tests/integration/test_deployment_bootstrap_assets.py -q`

## Evaluator Note
A separate evaluator subagent is currently unavailable because the account hit its usage limit. This sprint uses a local contract review plus the listed regression tests.

## Done When
- Weekday scheduling decisions are Pacific-time based.
- Boundary regression tests pass.
- The generated wrapper and Python delivery scheduler agree on day classification.
