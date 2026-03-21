---
name: iterative-agent-harness
description: Bootstrap and run a long-running multi-session coding workflow using an initializer, a machine-readable task list, a progress log, and one bounded engineering task per session. Use when a user wants agent-driven implementation to proceed incrementally across many context windows or across multiple repos.
---

# Iterative Agent Harness

Use this skill when the work is too large for one session and needs a durable handoff pattern across context windows.

This skill follows the harness pattern Anthropic described on November 26, 2025 in "Effective harnesses for long-running agents": an initializer creates durable repo artifacts, then each later coding session makes one bounded increment and leaves the repo clean for the next session.

## Create The Harness

Add these repo artifacts first:
- `agent_tasks.json`: machine-readable task list with IDs, dependencies, status, test command, integration test, and done criteria.
- `agent_progress.md`: append-only session log with context, files changed, tests run, outcome, open risks, and next task.
- `init.sh`: lightweight bootstrap that prints repo path, recent progress, and the next available task.

Keep task definitions dependency-ordered and small enough that one session can implement, test, and commit them cleanly.

If the repo does not have these files yet, you can scaffold them by running:

```bash
python skills/iterative-agent-harness/scripts/generate_harness.py \
  --project my-project \
  --features-file /path/to/features.txt \
  --output-dir /path/to/repo
```

The features file should contain one high-level requirement per line. The generator creates:
- `T0` for harness and test scaffolding
- one task per feature, chained in order
- one final cleanup and rollout task

## Task File Rules

`agent_tasks.json` should include:
- `version`
- `project`
- `updated_at`
- `session_contract`
- `tasks`

Each task should include:
- `id`
- `title`
- `status`: `pending` or `completed`
- `depends_on`
- `scope`
- `artifacts`
- `test_command`
- `integration_test`
- `done_when`

Prefer tasks that produce one meaningful architectural step and one end-to-end test.

## Session Contract

Every coding session should:
1. Run `pwd`.
2. Read `agent_progress.md`.
3. Read `agent_tasks.json`.
4. Run `./init.sh`.
5. Pick exactly one `pending` task whose dependencies are complete.
6. Implement only that task plus minimal prerequisite refactors.
7. Add or update the task's integration test before marking it done.
8. Run the task's listed test command and any necessary regression tests.
9. Commit the completed task with a descriptive non-interactive git commit message.
10. Update `agent_tasks.json`.
11. Append a new entry to `agent_progress.md`.
12. Leave the repo clean, with the next recommended task named explicitly.

Do not batch multiple tasks into one session unless the user explicitly changes the harness.

## Task Sizing

Good tasks:
- introduce one interface boundary
- add one storage or job primitive
- switch one subsystem from old architecture to new architecture
- add one admin/config surface
- add one persona or prompt feature
- add one final cleanup or rollout task

Bad tasks:
- "refactor everything"
- "finish the project"
- mixed fetch, storage, UI, and rollout changes in one step

If a task cannot end with a passing integration test and a clean commit, split it.

## Quality Bar

- Each task must end in a mergeable state.
- Integration tests are mandatory for every task.
- Progress notes should capture real risks, not generic summaries.
- The repo should always be runnable at the start of the next session.
- Prefer compatibility shims during migration; remove dead paths only in the final cleanup task.

## Resources

- For starter structure and copyable templates, read `references/harness-template.md`.
- For deterministic scaffold generation, use `scripts/generate_harness.py`.
