from __future__ import annotations

import os
from collections import deque
from pathlib import Path
from threading import Lock


DEBUG_LOG_TOKEN_HEADER = "X-Debug-Log-Token"
DEFAULT_DEBUG_LOG_LINES = 200
MAX_DEBUG_LOG_LINES = 500
_APPEND_LOCK = Lock()


def configured_debug_log_token() -> str:
    return os.getenv("CURATOR_DEBUG_LOG_TOKEN", "").strip()


def configured_debug_log_path() -> Path | None:
    raw_path = os.getenv("CURATOR_DEBUG_LOG_PATH", "").strip()
    if not raw_path:
        return None
    return Path(raw_path).expanduser()


def _path_has_symlink_component(path: Path) -> bool:
    for candidate in [path, *path.parents]:
        try:
            if candidate.is_symlink():
                return True
        except OSError:
            return True
    return False


def validate_configured_debug_log_path(path: Path | None) -> tuple[Path | None, str]:
    if path is None:
        return None, "missing"
    if not path.is_absolute():
        return None, "relative"
    if _path_has_symlink_component(path):
        return None, "symlink"
    try:
        if path.exists():
            if not path.is_file():
                return None, "not_file"
            return path, "ok"
        parent = path.parent
        if not parent.exists():
            return None, "parent_missing"
        if not parent.is_dir():
            return None, "parent_not_dir"
    except OSError:
        return None, "unreadable"
    return path, "ok"


def append_debug_log_line(line: str) -> None:
    path, status = validate_configured_debug_log_path(configured_debug_log_path())
    if path is None or status != "ok":
        return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = line if line.endswith("\n") else f"{line}\n"
        with _APPEND_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(rendered)
    except OSError:
        return


def parse_debug_log_line_count(raw_value: str | None) -> int:
    if raw_value is None or not str(raw_value).strip():
        return DEFAULT_DEBUG_LOG_LINES
    try:
        parsed = int(str(raw_value).strip())
    except ValueError as exc:
        raise ValueError(f"lines must be an integer between 1 and {MAX_DEBUG_LOG_LINES}.") from exc
    if parsed < 1:
        raise ValueError(f"lines must be an integer between 1 and {MAX_DEBUG_LOG_LINES}.")
    return min(parsed, MAX_DEBUG_LOG_LINES)


def read_debug_log_tail(path: Path, *, lines: int) -> tuple[list[str], bool]:
    buffer: deque[str] = deque(maxlen=lines + 1)
    with _APPEND_LOCK:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                buffer.append(raw_line.rstrip("\n"))
    truncated = len(buffer) > lines
    if truncated:
        buffer.popleft()
    return list(buffer), truncated
