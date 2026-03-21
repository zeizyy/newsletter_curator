#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_FILE="$ROOT_DIR/agent_tasks.json"
PROGRESS_FILE="$ROOT_DIR/agent_progress.md"

echo "repo: $ROOT_DIR"
echo "progress_file: $PROGRESS_FILE"
echo "task_file: $TASK_FILE"

if [[ ! -f "$TASK_FILE" ]]; then
  echo "agent_tasks.json not found"
  exit 1
fi

if [[ ! -f "$PROGRESS_FILE" ]]; then
  echo "agent_progress.md not found"
  exit 1
fi

echo
echo "recent progress:"
tail -n 12 "$PROGRESS_FILE" || true

echo
echo "next available tasks:"
python3 - <<'PY'
import json
from pathlib import Path

task_file = Path("agent_tasks.json")
data = json.loads(task_file.read_text(encoding="utf-8"))
tasks = data.get("tasks", [])
done = {task["id"] for task in tasks if task.get("status") == "completed"}

available = []
for task in tasks:
    if task.get("status") != "pending":
        continue
    deps = task.get("depends_on", [])
    if all(dep in done for dep in deps):
        available.append(task)

if not available:
    print("  none")
else:
    for task in available:
        print(f"  {task['id']}: {task['title']}")
        print(f"    test: {task['test_command']}")
PY

echo
echo "session reminder:"
echo "  1. Pick exactly one available task."
echo "  2. Add or update its integration test."
echo "  3. Run the listed test command."
echo "  4. Update agent_tasks.json and append to agent_progress.md."
