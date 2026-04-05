# Sprint Contract: T70 Opt-in PDF Delivery Format

## Objective
Add an opt-in PDF delivery format for subscriber profiles so Kindle-oriented readers can receive the daily newsletter as a PDF attachment, while existing subscribers continue receiving the standard email digest by default.

## Scope
- Add a `delivery_format` field to subscriber profiles with supported values `email` and `pdf`, defaulting to `email`.
- Add a compatible repository migration so existing databases gain the new field without forcing a schema reset, and treat missing legacy values as `email`.
- Expose the delivery-format choice on `/settings` and persist it in SQLite alongside `persona_text` and `preferred_sources`.
- Generate valid PDF bytes from the canonical ranked newsletter content already used for email delivery. The PDF must preserve story order and the same summary text as the email render payload.
- For subscribers with `delivery_format=pdf`, send a Gmail message with a short plain-text note plus one `application/pdf` attachment instead of the full HTML digest body.
- Keep ranking, summarization, newsletter selection, preview behavior, and standard email delivery unchanged for non-PDF subscribers in this sprint.

## Acceptance Criteria
- Existing subscribers and profiles without the new field continue to resolve to `delivery_format=email` with no settings migration step required from the reader.
- `/settings` shows the current delivery format, persists changes, and reloads with the saved choice.
- The PDF path produces valid PDF bytes from canonical newsletter content, and extracted text proves the same story titles appear in the same ranked order as the email content.
- Subscribers with `delivery_format=pdf` receive the PDF-attachment path only, while subscribers with `delivery_format=email` continue receiving the existing plain-text and HTML digest email.
- Delivery grouping or caching remains correct when identical personas differ only by delivery format.

## Test Coverage
- Add `tests/integration/test_subscriber_pdf_delivery_opt_in.py`.
- Cover settings persistence so a logged-in subscriber can save `delivery_format=pdf` and reload it.
- Cover repository migration or legacy-row fallback so profiles missing `delivery_format` still read back as `email`.
- Cover mixed delivery routing so a PDF subscriber gets a message with a PDF attachment and no HTML digest body, while an email subscriber still gets the existing body and HTML output.
- Extract the generated PDF in test code to verify it contains the canonical ranked story titles in order.

## Test Command
`uv run pytest tests/integration/test_subscriber_pdf_delivery_opt_in.py tests/integration/test_subscriber_settings_page_persists_profile.py tests/integration/test_delivery_personalizes_by_subscriber_profile.py tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py -q`

## Evaluator Fail Conditions
- Any existing non-PDF subscriber stops receiving the current email body or HTML digest.
- Existing repositories require a destructive schema reset just to add the new field.
- The saved profile does not round-trip `delivery_format` correctly through the settings page.
- The PDF attachment is missing, not `application/pdf`, not parseable as a PDF, or does not match the canonical story order and content.
- Delivery caching or grouping ignores delivery format and sends the wrong artifact type to a subscriber.

## Evaluation
- Status: PASS
- Date: 2026-04-04
- Evidence:
  - `uv run pytest tests/integration/test_subscriber_pdf_delivery_opt_in.py tests/integration/test_subscriber_settings_page_persists_profile.py tests/integration/test_delivery_personalizes_by_subscriber_profile.py tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py -q`
  - `uv run pytest tests/integration/test_subscriber_settings_page_persists_profile.py tests/integration/test_delivery_personalizes_by_subscriber_profile.py tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py tests/integration/test_buttondown_recipient_resolution.py tests/integration/test_deliver_digest_dry_run_recipient_override.py -q`
  - `git diff --check`
- Residual Risk:
  - `main.preview_job` still captures sends with a helper that does not accept attachments, so PDF-preview behavior is not covered by this sprint's contract or tests.
