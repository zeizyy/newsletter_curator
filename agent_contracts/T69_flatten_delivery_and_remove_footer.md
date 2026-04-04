# Sprint Contract: T69 Flatten Delivery And Remove Footer

## Objective
Render the final newsletter as one flat ranked story list with no category grouping, and remove the AI Signal Daily footer or signup CTA from both plain-text and HTML delivery output.

## Scope
- Treat the accepted story order from the pipeline as the canonical delivery order for both plain-text and HTML output.
- Remove category-section assembly from the final plain-text digest body.
- Remove category headers from rendered newsletter HTML so the email reads as one continuous ranked list of story cards.
- Stop appending the Buttondown signup CTA or the extra AI Signal Daily footer line during fresh sends and cached resend paths.
- Preserve cached newsletter reuse, preview rendering, and stored newsletter compatibility for rows that still contain the older grouped render payload.
- Keep personalization, recipient resolution, tracking, and non-delivery admin surfaces unchanged in this sprint.

## Acceptance Criteria
- Freshly generated newsletters render stories in ranked order with no section headings in `body`, `html_body`, or preview rerenders.
- Fresh sends persist newsletter rows without any Buttondown signup CTA or extra footer line in plain text or HTML.
- Cached sends reuse stored newsletters without adding the CTA back in memory.
- Existing stored newsletters that only have legacy grouped render payloads still rerender successfully in preview and send paths after the renderer change, but the rerendered output follows the new flat presentation.

## Test Coverage
- Add `tests/integration/test_final_delivery_flat_ranking_no_footer.py`.
- Cover fresh generation to verify the plain-text body, persisted HTML, and sent HTML are flat and contain no CTA/footer text.
- Cover cached newsletter reuse so a stored row created by the new flow stays footer-free on resend.
- Cover preview or rerender parity using stored render payloads so flat ordering remains consistent when HTML is regenerated from cached content.

## Test Command
`uv run pytest tests/integration/test_final_delivery_flat_ranking_no_footer.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_newsletter_rendering_selected_theme.py -q`

## Evaluator Fail Conditions
- Any plain-text digest still inserts category headers or section separators between stories.
- Any rendered HTML still shows category title blocks or the extra AI Signal Daily footer line.
- The Buttondown signup CTA appears in fresh or cached send output.
- Stored-newsletter preview or cached delivery rerendering breaks because the render payload shape is no longer understood.

## Evaluation
- Status: PASS
- Date: 2026-04-04
- Evidence:
  - `uv run pytest tests/integration/test_final_delivery_flat_ranking_no_footer.py tests/integration/test_preview_and_delivery_reuse_persisted_daily_newsletter.py tests/integration/test_newsletter_rendering_selected_theme.py tests/integration/test_delivery_uses_db_backed_subscriber_profiles.py tests/integration/test_delivery_personalizes_by_subscriber_profile.py tests/integration/test_admin_ui_e2e_harness.py -q`
  - `git diff --check`
  - Evaluator review confirmed the flat render payload works for fresh and cached newsletters, preview and delivery rerenders no longer show category headers, and the footer or Buttondown CTA is absent from the new canonical output.
- Residual Risk:
  - Legacy stored newsletter rows without `render_groups` still fall back to their stored `body` and `html_body`, so fully canonical rerendering still depends on cached render payload availability.
