# Sprint Contract: T59 Subscriber Settings Persistence

## Objective
Add a subscriber settings page in the existing Flask app and persist `persona_text` plus `preferred_sources` in SQLite, without changing delivery reads yet.

## Scope
- Add a new `subscriber_profiles` table rather than mutating `subscribers`, so the repo can add settings without destructive schema-reset risk.
- Add authenticated `GET` and `POST` `/settings` routes that use the existing subscriber session cookie from `T58`.
- Persist exactly two editable settings now: `persona_text` and `preferred_sources`.
- Build the preferred-source picker from the existing SQLite source catalog.
- Preserve previously saved sources that are now admin-disabled by rendering them as unavailable and keeping them saved on submit.

## Acceptance Criteria
- A logged-in subscriber can open `/settings`.
- The page renders the saved `persona_text` and selected preferred sources.
- Submitting the form updates the SQLite profile row for that subscriber.
- Saved settings persist across reloads and across new sessions.
- Unauthenticated requests are redirected to `/login`.
- Disabled preferred sources remain visible as unavailable and are not silently dropped on save.
- Delivery behavior is unchanged in this sprint.

## Test Coverage
- Add `tests/integration/test_subscriber_settings_page_persists_profile.py`.
- Seed a small source catalog in SQLite, including at least one admin-disabled source.
- Authenticate a subscriber through a stored session.
- Assert `GET /settings` renders the current values and disabled-source state.
- Assert `POST /settings` stores trimmed `persona_text`, normalizes preferred sources, and preserves disabled previously saved selections.
- Assert reloads and a new session still show the saved values.
- Assert unauthenticated access redirects to `/login`.

## Test Command
`uv run pytest tests/integration/test_subscriber_settings_page_persists_profile.py -q`

## Evaluator Fail Conditions
- The sprint mutates delivery personalization reads.
- Preferred sources are persisted outside SQLite.
- Disabled saved sources disappear silently on save.
- Unauthenticated access reaches `/settings`.

## Evaluation
- Status: PASS
- Date: 2026-03-28
- Evidence:
  - `uv run pytest tests/integration/test_subscriber_settings_page_persists_profile.py -q`
  - `uv run pytest tests/integration/test_subscriber_login_and_session_flow.py -q`
  - `uv run pytest tests/integration/test_admin_config_page_uses_shared_shell.py -q`
  - Evaluator review confirmed the new `subscriber_profiles` table, authenticated `/settings` flow, and disabled-source preservation behavior.
- Residual Risk:
  - Disabled saved sources are preserved as unavailable for now. A later delivery-migration task still needs to define exactly how those saved preferences interact with DB-backed delivery once the DB becomes the delivery source of truth.
