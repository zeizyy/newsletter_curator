# Sprint Contract: T58 Subscriber Login and Session Storage

## Objective
Add passwordless subscriber login to the existing Flask app using SQLite-backed one-time login tokens and persistent sessions, without introducing subscriber settings editing or delivery reads yet.

## Scope
- Add repository tables for subscriber identity, one-time login tokens, and persistent subscriber sessions.
- Add subscriber-facing login routes in `admin_app.py` using magic-link auth with hashed tokens at rest.
- Attempt to send login links through the existing Gmail send capability when credentials are available.
- Preserve an explicit offline and debug path that exposes the login link in the response for tests and local runs.
- Keep operator auth via `CURATOR_ADMIN_TOKEN` separate and unchanged.

## Acceptance Criteria
- `POST /login` accepts an email address, creates or reuses a subscriber row, and issues a one-time login token stored only as a hash in SQLite.
- When Gmail credentials are available, the app attempts to send the login link by email.
- In offline or debug mode, the login response can expose the raw magic link so the flow is testable without network access.
- `GET /login/confirm?token=...` consumes the token exactly once, creates a persistent subscriber session row in SQLite, and sets an HttpOnly cookie.
- `GET /account` requires a valid subscriber session and redirects unauthenticated users back to `/login`.
- `GET /logout` or `POST /logout` revokes the session and clears the subscriber cookie.
- Invalid, expired, or reused tokens are rejected.
- No raw passwords are stored anywhere.

## Test Coverage
- Add `tests/integration/test_subscriber_login_and_session_flow.py`.
- Assert login requests create subscriber and login-token rows and that token hashes, not raw tokens, are stored at rest.
- Assert the app attempts Gmail-backed login delivery through a monkeypatched helper when email delivery is available.
- Assert the offline exposed-link path can complete the full login flow, reach `/account`, log out, and reject token reuse.
- Assert subscriber auth does not bypass operator admin-token auth.

## Test Command
`uv run pytest tests/integration/test_subscriber_login_and_session_flow.py -q`

## Evaluator Fail Conditions
- The app never attempts real email delivery for login links when credentials are available.
- Raw login tokens or raw session tokens are stored in SQLite.
- Tokens can be reused after successful confirmation.
- Subscriber sessions unlock operator routes protected by `CURATOR_ADMIN_TOKEN`.
- The sprint spills into settings editing or delivery-personalization reads.

## Evaluation
- Status: PASS
- Date: 2026-03-28
- Evidence:
  - `uv run pytest tests/integration/test_subscriber_login_and_session_flow.py -q`
  - `uv run pytest tests/integration/test_admin_config_page_uses_shared_shell.py -q`
  - Evaluator review confirmed the SQLite-backed subscriber identity, one-time token, and session flow, plus the Gmail-attempt and offline fallback paths.
- Residual Risk:
  - The login-email path still depends on the server's existing Gmail OAuth token setup. A misconfigured mail environment will fall back to the offline or debug path when enabled, or show an error instead of sending mail.
