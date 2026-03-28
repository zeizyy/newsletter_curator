# Sprint Contract: T62 Subscriber Personalization Cleanup

## Objective
Make SQLite the only source of subscriber personalization data, remove legacy Buttondown and YAML personalization reads, and document the operator rollout for the DB-backed subscriber flow.

## Scope
- Keep recipient membership resolution unchanged: `--dry-run-recipient`, then Buttondown active subscribers, then `email.digest_recipients`.
- Keep Buttondown as the source of truth for deliverability filtering only when Buttondown is the active recipient source.
- Remove Buttondown metadata lookups from delivery personalization.
- Remove `config.yaml` `subscribers` overrides from delivery personalization.
- Treat SQLite profile values as authoritative.
- If a SQLite profile has blank `persona_text`, fall back only to the global `persona.text`.
- If a SQLite profile has blank `preferred_sources`, treat that as no per-user source filter.
- Automatically upsert bare `subscribers` rows for resolved recipients during delivery so rollout can proceed safely before every user has created a profile.
- Do not auto-backfill persona or preferred-source data from Buttondown or YAML into SQLite in this sprint.
- Update `README.md` to describe DB-backed personalization, rollout, verification, and rollback expectations.

## Acceptance Criteria
- Delivery personalization reads only from SQLite.
- Resolved recipients without a profile row still receive delivery safely using the global default persona and no preferred-source filter.
- Buttondown metadata no longer changes `persona_text` or `preferred_sources`.
- YAML `subscribers` entries no longer change `persona_text` or `preferred_sources`.
- README explains recipient discovery, DB-backed personalization, rollout verification, and rollback behavior clearly.

## Test Coverage
- `tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py`
- `tests/integration/test_subscriber_settings_page_persists_profile.py`
- Update the older recipient-resolution and personalized-cache tests so they seed SQLite profiles instead of legacy YAML or Buttondown personalization inputs.

## Test Command
`uv run pytest tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py tests/integration/test_subscriber_settings_page_persists_profile.py -q`

## Evaluator Fail Conditions
- Delivery still reads personalization from Buttondown metadata or YAML subscriber overrides.
- Resolved recipients without a SQLite profile are skipped instead of safely receiving the default variant.
- Delivery eligibility changes away from the current Buttondown-first or config-fallback behavior.
- README rollout guidance is missing verification or rollback details.

## Evaluation
- Status: PASS
- Date: 2026-03-28
- Evidence:
  - `uv run pytest tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py tests/integration/test_subscriber_settings_page_persists_profile.py -q`
  - `uv run pytest tests/integration/test_buttondown_recipient_resolution.py tests/integration/test_deliver_digest_dry_run_recipient_override.py tests/integration/test_delivery_personalizes_by_subscriber_profile.py tests/integration/test_personalized_newsletter_cache_keys_by_profile.py -q`
  - Evaluator review confirmed delivery personalization now reads only from SQLite, recipient-membership safety remained intact, and the README rollout notes cover discovery order, verification, and rollback.
- Residual Risk:
  - Existing `config.yaml` files may still contain legacy `subscribers` entries even though delivery now ignores them. The new README documents that cleanup, but operators still need to remove those stale blocks manually from long-lived configs.
