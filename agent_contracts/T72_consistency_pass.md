# Sprint Contract: T72 README, Default Config, and UI Consistency Pass

## Objective
Remove the drift that has built up between the current implementation, the checked-in `config.yaml`, the README, the admin/subscriber copy, and the preview or delivery artifacts so operators and readers see one coherent product story.

## Scope
- Update `README.md` to match the current delivery and personalization behavior, especially:
  - `preferred_sources` as a soft final-ranking signal instead of a hard pre-ranking filter,
  - persona affecting only the final ranking or selection pass,
  - tracking base URL resolution using only `tracking.base_url` or `CURATOR_PUBLIC_BASE_URL`,
  - the checked-in config and rollout caveats around subscriber settings, preview, and PDF delivery.
- Update the checked-in `config.yaml` so the default repo config does not silently enable telemetry without an explicit public host, and explicitly carry the checked-in values for:
  - `database.newsletter_ttl_days`
  - `database.allow_schema_reset`
  - `email.digest_subject`
  - `tracking.enabled`
  - `tracking.open_enabled`
  - `tracking.click_enabled`
  - `tracking.base_url`
- Normalize config fallbacks so `config.yaml`, `curator/config.py`, and admin-form blank-save behavior agree on:
  - runtime fallback `additional_sources.max_total`
  - checked-in digest-subject defaults
  - the removal of legacy YAML personalization overrides from the checked-in config.
- Correct admin and subscriber settings copy so it matches the implementation:
  - operator persona copy should describe final-ranking-only influence,
  - subscriber persona and preferred-source copy should describe personalized final selection, not ingest or repository filtering.
  - operator delivery-recipient copy should make Buttondown precedence explicit instead of implying `email.digest_recipients` is always the live audience.
- Bring preview or artifact surfaces back into sync with delivery:
  - email-safe preview should re-render with the same subscriber settings link logic as delivered email,
  - preview labels should distinguish between browser-first review layouts and the actual email-safe delivery artifact,
  - preview capture should preserve PDF-attachment metadata if a send path produces it,
  - PDF-facing naming or metadata should match the current product language instead of stale internal labels where that would confuse readers.
- Adopt an explicit product-language split instead of leaving the current accidental mix:
  - `Newsletter Curator` stays the app and account-management product name,
  - `AI Signal Daily` stays the reader-facing digest title,
  - `email.digest_subject` remains the configurable subject line rather than the hard-coded artifact masthead.
- Keep repository selection logic, delivery grouping, and canonical newsletter content unchanged outside the consistency fixes above.

## Acceptance Criteria
- README statements about personalization, telemetry, and checked-in defaults match the code and checked-in config.
- The checked-in `config.yaml` no longer enables telemetry by default when no public host is configured.
- A blank-save admin form round trip keeps `additional_sources.max_total`, tracking behavior, and digest-subject defaults aligned with the canonical config rules.
- Subscriber and admin settings pages no longer say persona or preferred sources affect ingest scoring, stored summaries, or the repository intake pool.
- Admin delivery-recipient copy explains that Buttondown active subscribers override `email.digest_recipients` when `BUTTONDOWN_API_KEY` is configured.
- `/preview?template=email_safe` renders the same settings-link header behavior as the delivered email-safe HTML.
- Preview surfaces clearly separate browser-review markup from the actual email-safe delivery artifact, any generated PDF artifact metadata is not silently discarded by `main.preview_job`, and the app-vs-digest naming split is consistent.

## Test Coverage
- Update `tests/integration/test_subscriber_settings_page_persists_profile.py` so the assertions reflect the corrected subscriber copy.
- Update `tests/integration/test_admin_preview_renders_digest.py` to cover the email-safe settings link and the clarified preview labeling.
- Add or extend an admin-config regression so Buttondown-precedence copy on the control-room delivery section is asserted directly.
- Add a preview-capture regression that calls `main.preview_job()` through a PDF-capable send function signature and fails if attachment metadata is still discarded.
- Add or extend a config-parity regression to verify the checked-in config keeps telemetry off until explicitly configured, the legacy `subscribers` YAML block is gone from the checked-in config, the newly explicit database and tracking knobs are present, and admin-form fallbacks keep `additional_sources.max_total` aligned.
- Keep PDF-delivery coverage in the targeted test command so preview or artifact changes do not regress attachment generation.

## Test Command
`uv run pytest tests/integration/test_config_and_preview_consistency.py tests/integration/test_admin_config_page_uses_shared_shell.py tests/integration/test_admin_preview_renders_digest.py tests/integration/test_subscriber_settings_page_persists_profile.py tests/integration/test_subscriber_pdf_delivery_opt_in.py -q`

## Evaluator Fail Conditions
- README still documents a behavior the code no longer uses, especially around `preferred_sources`, tracking base URL fallback, or preview caveats.
- The checked-in config still has telemetry enabled by default without a valid explicit public-host configuration.
- Admin blank-save fallback still writes `additional_sources.max_total=20` or another value that disagrees with the intended checked-in default.
- Any settings page still claims persona or preferred sources change ingest or repository filtering.
- Operator recipient copy still implies `email.digest_recipients` is always the live audience when Buttondown takes precedence.
- Email-safe preview still omits the header settings link or uses labels that imply the wrong artifact is the one actually delivered.
- `main.preview_job()` still drops attachment metadata when the send callback accepts `attachments`.
- PDF attachment behavior or canonical delivery content regresses while making the consistency changes.

## Evaluation
- Status: PASS
- Date: 2026-04-05
- Evidence:
  - `uv run pytest tests/integration/test_config_and_preview_consistency.py tests/integration/test_admin_config_page_uses_shared_shell.py tests/integration/test_admin_preview_renders_digest.py tests/integration/test_subscriber_settings_page_persists_profile.py tests/integration/test_subscriber_pdf_delivery_opt_in.py -q`
  - `uv run pytest tests/integration/test_delivery_public_host_links_and_fallback.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_default_config_includes_repo_persona.py -q`
  - `python3 -m json.tool agent_tasks.json >/dev/null`
  - `git diff --check`
- Residual Risk:
  - Preview still renders only the default audience variant, so personalized-profile preview remains a future enhancement rather than part of this consistency pass.
