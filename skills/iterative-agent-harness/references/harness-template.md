# Harness Template

Use this file when creating the first version of the harness.

## Feature Input Format

For automated scaffolding, provide a plain-text feature list with one item per line:

```text
Refactor the monolith into modules
Add persistence and migrations
Split fetch and delivery into separate jobs
Add admin source selection
Add persona-aware ranking
```

The generator will create `T0`, then one task per feature in order, then a final cleanup task.

## `agent_tasks.json`

```json
{
  "version": 1,
  "project": "your-project",
  "updated_at": "YYYY-MM-DD",
  "session_contract": [
    "Run `pwd`, read `agent_progress.md`, read `agent_tasks.json`, and run `./init.sh`.",
    "Pick exactly one pending task whose dependencies are complete.",
    "Implement only that task plus minimal prerequisite refactors required to finish it cleanly.",
    "Add or update the task's integration test before marking the task complete.",
    "Run the task's listed test command and any necessary regression tests.",
    "Commit the completed task to git with a descriptive non-interactive commit message.",
    "Update `agent_tasks.json` status fields and append a concise entry to `agent_progress.md`.",
    "Leave the repository in a clean state with the next recommended task called out explicitly."
  ],
  "tasks": [
    {
      "id": "T0",
      "title": "Initialize the harness and offline test foundation",
      "status": "pending",
      "depends_on": [],
      "scope": [
        "Add test tooling",
        "Create integration test directories",
        "Add fake adapters and temp helpers"
      ],
      "artifacts": [
        "pyproject.toml",
        "tests/",
        "tests/integration/"
      ],
      "test_command": "uv run pytest tests/integration/test_smoke.py",
      "integration_test": "tests/integration/test_smoke.py",
      "done_when": [
        "The repo has a repeatable smoke test",
        "Future tasks have a working test harness"
      ]
    }
  ]
}
```

## `agent_progress.md`

```md
# Agent Progress

This file is append-only.

## Session Contract

1. Run `pwd`.
2. Read `agent_progress.md`.
3. Read `agent_tasks.json`.
4. Run `./init.sh`.
5. Choose exactly one pending task whose dependencies are complete.
6. Implement only that task plus minimal prerequisite refactors.
7. Add or update the task's integration test.
8. Run the task's test command and any needed regression tests.
9. Commit the completed task with a descriptive non-interactive commit message.
10. Update task status in `agent_tasks.json`.
11. Append a new entry here before ending the session.

## Session Log

### YYYY-MM-DD - T1 short title
- Context:
- Files changed:
- Tests run:
- Outcome:
- Open risks:
- Next recommended task:
```

## `init.sh`

Keep it simple. It should:
- print repo path
- print the progress file path and task file path
- show recent progress
- show the next available task and its test command

## Planning Heuristics

Use this split:
- `T0`: harness and tests
- `T1..Tn-1`: one architectural increment each
- final task: docs, dead-path removal, rollout cleanup, full end-to-end test

Good dependency patterns:
- refactor before persistence
- persistence before job split
- job split before admin/config UI
- offline fixtures before persona/prompt experiments
- all migrations complete before dead-path removal
