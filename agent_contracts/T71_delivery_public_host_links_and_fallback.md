# Sprint Contract: T71 Delivery Public Host Links and Fallback

## Objective
Add a subscriber settings link to the delivered newsletter header, resolve outbound newsletter links from explicit public-host config instead of localhost fallbacks, and keep a direct original-article path visible in delivered HTML so readers can still reach the source if the tracking redirect host is unavailable.

## Scope
- Add a subscriber settings link to delivered newsletter output in the header area before the first story card.
- Resolve outbound newsletter links from `tracking.base_url` first, then `CURATOR_PUBLIC_BASE_URL`.
- Remove the delivery-time fallback that synthesizes `127.0.0.1` or the admin bind host from `CURATOR_ADMIN_HOST` and `CURATOR_ADMIN_PORT`.
- If no public host is configured, skip open-pixel injection and click-link rewriting so outbound mail keeps original article URLs instead of dead tracking URLs.
- Prepend `Manage your settings: <url>` to the plain-text delivery body when a public host is configured, and omit that line when no public host is configured.
- Preserve a visible direct original-article fallback link in delivered HTML alongside the tracked CTA, and mark it so tracking rewrites do not mutate it.
- Apply the link-hardening behavior to the delivered email-safe HTML variant used by the delivery job.
- Keep PDF generation, subscriber settings persistence, tracking endpoint routes, and canonical newsletter content otherwise unchanged.

## Acceptance Criteria
- When `tracking.base_url` or `CURATOR_PUBLIC_BASE_URL` is configured, delivered newsletter output contains a settings link before the first story card that points to `/settings` on that host.
- When a public host is configured and telemetry is enabled, open-pixel and tracked-click URLs use that host and do not use localhost or the admin bind host.
- When no public host is configured, delivered HTML contains original article URLs, contains no `/track/open/` pixel, and contains no `/track/click/` links.
- Delivered HTML includes both a tracked article CTA and a separate direct fallback article link, and only the tracked CTA is rewritten.
- Plain-text delivery remains readable and continues to expose the original article URLs; PDF attachment behavior remains unchanged.

## Test Coverage
- Add `tests/integration/test_delivery_public_host_links_and_fallback.py`.
- Cover a delivery run with telemetry enabled and an explicit public host, asserting:
  - the settings link renders before the first story card,
  - the tracked click URLs and open pixel use the configured host,
  - the direct fallback link still points to the original article URL,
  - the plain-text body exposes the settings URL near the top.
- Cover a delivery run with telemetry enabled but no public host configured, asserting:
  - no localhost or admin-bind-host URL is emitted,
  - no tracking pixel or tracked click URL is emitted,
  - original article links remain intact.
- Keep regression coverage for tracking endpoints, the cached delivery path, and PDF-attachment delivery in the test command.

## Test Command
`uv run pytest tests/integration/test_delivery_public_host_links_and_fallback.py tests/integration/test_newsletter_telemetry_tracking_endpoints.py tests/integration/test_delivery_tracking_disabled_by_default.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_subscriber_pdf_delivery_opt_in.py -q`

## Evaluator Fail Conditions
- Any delivered newsletter HTML still emits a localhost or admin-bind-host tracking URL.
- The settings link is missing, hardcoded, or appears after the first story card.
- The direct fallback link is absent or gets rewritten to the tracked URL.
- Delivery still injects telemetry links when no public host is configured.
- Plain-text or PDF delivery regresses outside the intended link hardening changes.

## Evaluation
- Status: PASS
- Date: 2026-04-04
- Evidence:
  - `uv run pytest tests/integration/test_delivery_public_host_links_and_fallback.py tests/integration/test_newsletter_telemetry_tracking_endpoints.py tests/integration/test_delivery_tracking_disabled_by_default.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_subscriber_pdf_delivery_opt_in.py -q`
  - `python3 -m json.tool agent_tasks.json >/dev/null`
  - `git diff --check`
- Residual Risk:
  - `admin_app.py` still renders `/preview?template=email_safe` without passing the new `settings_url`, so delivered email and admin email-safe preview are not yet fully aligned on the new header link.
