# Sprint Contract: T60 DB-Backed Delivery And Signup CTA

## Objective
Switch delivery personalization to prefer SQLite-backed subscriber profiles over Buttondown or YAML fallbacks, and append the newsletter signup CTA exactly once to both the plain-text and HTML email output.

## Scope
- Keep recipient selection unchanged in this sprint: Buttondown remains first, then config fallback, with `recipient_override` still forcing a single-recipient send.
- Resolve personalization in this order for each resolved recipient: SQLite `subscriber_profiles` row first, then Buttondown metadata persona, then YAML/config fallback.
- Treat an existing SQLite profile row as authoritative for both fields together.
- If the SQLite profile row has a blank `persona_text`, fall back only to the global default persona, not to Buttondown or YAML persona overrides.
- If the SQLite profile row has an empty `preferred_sources` list, treat that as no preferred-source filter, not as a fallback trigger.
- Keep personalized cache identity keyed by the existing `profile_key`, so profile changes continue to produce distinct audience cache keys.
- Append the signup CTA before any send-time tracking HTML rewriting.
- Persist freshly generated newsletters with the CTA already included.
- For cached newsletters that predate this rollout, append the CTA only in memory at send time and do not rewrite the stored row.
- Do not change login/settings UI, migration cleanup, or persona/discovery tuning in this sprint.

## Acceptance Criteria
- A recipient with a stored SQLite profile receives that profile's persona and preferred sources during delivery, even when Buttondown metadata or YAML overrides disagree.
- A recipient without a stored SQLite profile still uses the existing Buttondown and YAML fallback behavior.
- `recipient_override` still resolves one recipient and still applies DB-first personalization for that email.
- Recipient selection remains Buttondown-first with config fallback and does not start sourcing recipients from SQLite in this sprint.
- Fresh sends include the CTA once in `body` and once in `html_body`.
- Fresh sends persist CTA-inclusive newsletter rows, and cached resend paths do not duplicate the CTA.
- Pre-existing cached newsletter rows without the CTA are decorated only at send time, while the stored row remains unchanged.

## Test Coverage
- Add `tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py`.
- Add `tests/integration/test_newsletter_footer_signup_cta.py`.
- Cover DB-backed personalization precedence over conflicting Buttondown and YAML data.
- Cover fallback behavior for an unprofiled subscriber.
- Cover `recipient_override` with DB-first personalization.
- Cover fresh-send CTA persistence and cached-send exact-once CTA decoration without mutating old stored rows.

## Test Command
`uv run pytest tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py tests/integration/test_newsletter_footer_signup_cta.py -q`

## Evaluator Fail Conditions
- Recipient selection changes away from Buttondown-first then config fallback.
- Delivery ignores a stored SQLite profile when one exists for a recipient.
- Blank or empty SQLite profile values unexpectedly fall back to Buttondown or YAML overrides.
- The CTA is missing from plain text or HTML, or appears more than once in either path.
- Fresh newsletter rows are persisted without the CTA.
- Pre-existing cached rows are rewritten in storage instead of being decorated only at send time.

## Evaluation
- Status: PASS
- Date: 2026-03-28
- Evidence:
  - `uv run pytest tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py tests/integration/test_newsletter_footer_signup_cta.py -q`
  - `uv run pytest tests/integration/test_delivery_personalizes_by_subscriber_profile.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_buttondown_recipient_resolution.py tests/integration/test_deliver_digest_dry_run_recipient_override.py -q`
  - `git diff --check`
  - Evaluator review confirmed recipient resolution stayed Buttondown-first then config fallback, DB-backed profiles override Buttondown and YAML personalization including `recipient_override`, fresh sends persist the CTA, and pre-existing cached rows only receive the CTA at send time.
- Residual Risk:
  - SQLite profile reads currently load all subscriber delivery profiles before per-recipient resolution. That remains acceptable for the current small subscriber set, but `T62` cleanup may want to tighten the read path if subscriber volume grows materially.
