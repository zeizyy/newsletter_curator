from __future__ import annotations

import json

from curator import observability


def test_emit_event_preserves_debug_log_when_stdout_breaks(monkeypatch, tmp_path):
    log_path = tmp_path / "debug.ndjson"
    monkeypatch.setenv("CURATOR_DEBUG_LOG_PATH", str(log_path))

    def broken_print(*args, **kwargs):
        raise BrokenPipeError("broken pipe")

    monkeypatch.setattr(observability, "print", broken_print, raising=False)

    observability.emit_event("stdout_broken", detail="kept")

    logged = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert logged[-1]["event"] == "stdout_broken"
    assert logged[-1]["detail"] == "kept"
