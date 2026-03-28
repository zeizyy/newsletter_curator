# Sprint Contract: T61 Persona And Discovery Tuning

## Objective
Restrict persona text so it only influences the final `select_top_stories` LLM call, while modestly widening the global ingest discovery budget to improve recall without changing final newsletter size or source quotas.

## Scope
- Keep persona text in the final delivery ranking or selection path only via `select_top_stories`.
- Remove persona influence from ingest-time cheap scoring via `score_story_candidates`.
- Remove persona influence from article summarization via `summarize_article_with_llm` and the development fake summarizer.
- Apply the discovery-budget increase globally to ingest jobs, not only to personalized delivery.
- Increase `additional_sources.max_total` from `20` to `30`.
- Increase `limits.max_gmail_fetch_after_score` from `12` to `18`.
- Keep `limits.final_top_stories`, `limits.select_top_stories`, and `limits.source_quotas` unchanged.
- Do not change delivery persistence, signup CTA behavior, or subscriber/profile storage in this sprint.

## Acceptance Criteria
- Two different personas can still produce different final newsletter selections through `select_top_stories`.
- Summaries for the same article are identical regardless of persona text.
- Ingest-time cheap scoring results are identical regardless of persona text.
- The default additional-source command now requests up to `30` stories.
- The default Gmail fetch-after-score stage now fetches up to `18` candidates.
- Final newsletter size and source quotas remain unchanged.

## Test Coverage
- Add `tests/integration/test_persona_only_affects_final_selection.py`.
- Add `tests/integration/test_discovery_fetch_budget_increases_recall.py`.
- Update obsolete persona tests so they match the new contract instead of the old persona-conditioned summary behavior.
- Assert persona appears in final ranking prompts but not in ingest scoring or summary prompts.
- Assert the Gmail fetch-after-score default increases to `18`.
- Assert the additional-source command default increases to `30`.

## Test Command
`uv run pytest tests/integration/test_persona_only_affects_final_selection.py tests/integration/test_discovery_fetch_budget_increases_recall.py -q`

## Evaluator Fail Conditions
- Persona text still affects `score_story_candidates` or `summarize_article_with_llm`.
- Persona no longer affects the final `select_top_stories` path.
- The discovery-budget increase does not land at exactly `30` additional-source max stories and `18` Gmail fetch-after-score candidates.
- `final_top_stories` or source quotas change in this sprint.
- The targeted tests do not pass cleanly.

## Evaluation
- Status: PASS
- Date: 2026-03-28
- Evidence:
  - `uv run pytest tests/integration/test_persona_only_affects_final_selection.py tests/integration/test_discovery_fetch_budget_increases_recall.py -q`
  - `uv run pytest tests/integration/test_persona_changes_ranking_and_summary.py tests/integration/test_gmail_prefetch_scoring_limits_article_fetches.py tests/integration/test_ingest_only_summarizes_top_twenty_scored_articles.py tests/integration/test_ingest_only_persists_top_twenty_summarized_articles.py -q`
  - `git diff --check`
  - Evaluator review confirmed persona only reaches `select_top_stories`, the discovery defaults landed at exactly `30` and `18`, and the updated persona tests align with the new contract.
- Residual Risk:
  - The widened discovery budget is limited to the current global defaults. If future operators already override `additional_sources.max_total` or `max_gmail_fetch_after_score` in their YAML, they will retain those values until `T62` rollout or manual config cleanup.
