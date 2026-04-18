# Newsletter Curator Agent Instructions

## Git Workflow
- `main` is protected and direct pushes are not allowed.
- When publishing changes, always push a branch, open a PR, wait for required checks, and merge the PR into `main`.
- Do not attempt direct `git push origin main` as a deployment path for this repository.

## Gmail Processing
- Do not process Gmail messages concurrently. Concurrent Gmail message processing can corrupt messages.
- The Gmail worker count is intentionally set to `1` because of that corruption risk.
