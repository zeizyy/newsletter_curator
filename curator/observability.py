from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
import subprocess
from uuid import uuid4

from .debug_logs import append_debug_log_line


_PROCESS_RUN_ID = uuid4().hex
_RECENT_EVENT_LINES: deque[str] = deque(maxlen=500)


def _event_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@lru_cache(maxsize=1)
def _git_sha() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = str(completed.stdout).strip()
    return sha or "unknown"


def emit_event(event: str, /, **payload) -> None:
    rendered = json.dumps(
        {
            "event": event,
            "ts": _event_timestamp(),
            "run_id": _PROCESS_RUN_ID,
            "git_sha": _git_sha(),
            **payload,
        }
    )
    _RECENT_EVENT_LINES.append(rendered)
    print(rendered, flush=True)
    append_debug_log_line(rendered)


def recent_event_lines(limit: int = 80) -> list[str]:
    if limit <= 0:
        return []
    return list(_RECENT_EVENT_LINES)[-limit:]


def compact_model_usage(usage_by_model: Mapping[str, object] | None) -> dict[str, dict[str, int]]:
    if not isinstance(usage_by_model, Mapping):
        return {}

    compact: dict[str, dict[str, int]] = {}
    for model_name, stats in usage_by_model.items():
        if not isinstance(stats, Mapping):
            continue
        compact[str(model_name)] = {
            "input": int(stats.get("input", 0) or 0),
            "output": int(stats.get("output", 0) or 0),
            "total": int(stats.get("total", 0) or 0),
        }
    return compact
