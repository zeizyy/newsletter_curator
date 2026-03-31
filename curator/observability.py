from __future__ import annotations

import json
from collections.abc import Mapping


def emit_event(event: str, /, **payload) -> None:
    print(json.dumps({"event": event, **payload}), flush=True)


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
