from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path


SESSION_CONTRACT = [
    "Run `pwd`, read `agent_progress.md`, read `agent_tasks.json`, and run `./init.sh`.",
    "Pick exactly one pending task whose dependencies are complete.",
    "Implement only that task plus minimal prerequisite refactors required to finish it cleanly.",
    "Add or update the task's integration test before marking the task complete.",
    "Run the task's listed test command and any necessary regression tests.",
    "Commit the completed task to git with a descriptive non-interactive commit message.",
    "Update `agent_tasks.json` status fields and append a concise entry to `agent_progress.md`.",
    "Leave the repository in a clean state with the next recommended task called out explicitly.",
]


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "project"


def read_features(path: Path) -> list[str]:
    lines = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*0-9.()\s]+", "", line).strip()
        if line:
            lines.append(line)
    if not lines:
        raise ValueError("features file did not contain any non-empty feature lines")
    return lines


def integration_test_name(task_id: str, title: str) -> str:
    slug = slugify(title).replace("-", "_")
    return f"tests/integration/test_{task_id.lower()}_{slug}.py"


def build_task(task_id: str, title: str, depends_on: list[str]) -> dict:
    test_path = integration_test_name(task_id, title)
    return {
        "id": task_id,
        "title": title,
        "status": "pending",
        "depends_on": depends_on,
        "scope": [
            f"Implement {title}",
            "Add any minimal supporting refactors needed to keep the repo clean",
            "Cover the behavior with an integration test",
        ],
        "artifacts": [
            "Update the relevant runtime modules for this task",
            test_path,
        ],
        "test_command": f"uv run pytest {test_path}",
        "integration_test": test_path,
        "done_when": [
            f"{title} is implemented end to end",
            "The task-specific integration test passes",
            "The repository is left in a clean, mergeable state",
        ],
    }


def build_tasks(features: list[str]) -> list[dict]:
    tasks = [
        {
            "id": "T0",
            "title": "Initialize the long-running agent harness",
            "status": "pending",
            "depends_on": [],
            "scope": [
                "Add or confirm test tooling",
                "Create integration test and fixture directories",
                "Add fake adapters and temp-config helpers",
                "Create the initial offline smoke test",
            ],
            "artifacts": [
                "agent_tasks.json",
                "agent_progress.md",
                "init.sh",
                "tests/",
                "tests/integration/",
            ],
            "test_command": "uv run pytest tests/integration/test_smoke.py",
            "integration_test": "tests/integration/test_smoke.py",
            "done_when": [
                "The repo has a repeatable smoke test",
                "The task harness files exist",
                "Future tasks have a working offline-first test foundation",
            ],
            "notes": "Initializer task. Do not start deeper architectural work before this is complete.",
        }
    ]

    previous_task = "T0"
    for index, feature in enumerate(features, start=1):
        task_id = f"T{index}"
        tasks.append(build_task(task_id, feature, [previous_task]))
        previous_task = task_id

    final_task_id = f"T{len(features) + 1}"
    tasks.append(
        {
            "id": final_task_id,
            "title": "Finalize rollout, remove dead paths, and run full end-to-end verification",
            "status": "pending",
            "depends_on": [previous_task],
            "scope": [
                "Remove obsolete compatibility paths",
                "Document the final architecture and operational flow",
                "Run a full end-to-end integration test",
            ],
            "artifacts": [
                "README.md",
                "final CLI entrypoints or docs",
                "tests/integration/test_full_pipeline.py",
            ],
            "test_command": "uv run pytest tests/integration/test_full_pipeline.py",
            "integration_test": "tests/integration/test_full_pipeline.py",
            "done_when": [
                "The implemented architecture matches the documented one",
                "Dead paths are removed",
                "A final full-pipeline integration test passes",
            ],
        }
    )
    return tasks


def build_progress_markdown(initial_task_id: str) -> str:
    return f"""# Agent Progress

This file is append-only. Each coding session should add a short dated entry with:
- task worked on
- files changed
- tests run
- outcome
- open risks
- next recommended task

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

## Initial Entry

### {date.today().isoformat()} - Harness initialized
- Context: Created the task harness files for an iterative long-running agent workflow.
- Files changed: `agent_tasks.json`, `agent_progress.md`, `init.sh`
- Tests run: artifact validation only
- Outcome: Follow-on coding agents now have a dependency-ordered task list and session contract.
- Open risks: The repository still needs the first executable engineering task completed.
- Next recommended task: `{initial_task_id}`

## Session Log

Add new entries below this line.
"""


def build_init_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
progress_file="$repo_dir/agent_progress.md"
task_file="$repo_dir/agent_tasks.json"

echo "repo: $repo_dir"
echo "progress_file: $progress_file"
echo "task_file: $task_file"
echo

if [[ -f "$progress_file" ]]; then
  echo "recent progress:"
  tail -n 20 "$progress_file"
  echo
fi

python3 - "$task_file" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)

completed = {task["id"] for task in data["tasks"] if task["status"] == "completed"}
available = [
    task for task in data["tasks"]
    if task["status"] == "pending" and set(task.get("depends_on", [])) <= completed
]

if not available:
    print("next available tasks: none")
else:
    print("next available tasks:")
    for task in available:
        print(f"  {task['id']}: {task['title']}")
        print(f"    test: {task['test_command']}")

print()
print("session reminder:")
for idx, item in enumerate(data.get("session_contract", []), start=1):
    print(f"  {idx}. {item}")
PY
"""


def write_file(path: Path, content: str, *, executable: bool = False, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists; pass --overwrite to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate iterative agent harness files.")
    parser.add_argument("--project", required=True, help="Project name for agent_tasks.json")
    parser.add_argument(
        "--features-file",
        required=True,
        type=Path,
        help="Plain-text file containing one high-level feature per line",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        type=Path,
        help="Directory to write agent_tasks.json, agent_progress.md, and init.sh into",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing harness files in the output directory",
    )
    args = parser.parse_args()

    features = read_features(args.features_file)
    tasks = build_tasks(features)
    payload = {
        "version": 1,
        "project": slugify(args.project),
        "updated_at": date.today().isoformat(),
        "session_contract": SESSION_CONTRACT,
        "tasks": tasks,
    }

    output_dir = args.output_dir.resolve()
    write_file(
        output_dir / "agent_tasks.json",
        json.dumps(payload, indent=2) + "\n",
        overwrite=args.overwrite,
    )
    write_file(
        output_dir / "agent_progress.md",
        build_progress_markdown("T0 Initialize the long-running agent harness"),
        overwrite=args.overwrite,
    )
    write_file(
        output_dir / "init.sh",
        build_init_script(),
        executable=True,
        overwrite=args.overwrite,
    )

    print(f"Generated harness in {output_dir}")
    print(f"Tasks: {len(tasks)}")


if __name__ == "__main__":
    main()
