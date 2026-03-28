from __future__ import annotations

import gc
import os
import resource
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime


def _max_rss_megabytes() -> float:
    raw_value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss or 0)
    if sys.platform == "darwin":
        rss_bytes = raw_value
    else:
        rss_bytes = raw_value * 1024.0
    return round(rss_bytes / (1024.0 * 1024.0), 2)


@dataclass(frozen=True)
class RuntimeCapture:
    started_at: str
    started_monotonic: float
    max_rss_mb_before: float
    gc_counts_before: tuple[int, int, int]


def start_runtime_capture() -> RuntimeCapture:
    return RuntimeCapture(
        started_at=datetime.now(UTC).isoformat(),
        started_monotonic=time.monotonic(),
        max_rss_mb_before=_max_rss_megabytes(),
        gc_counts_before=gc.get_count(),
    )


def finish_runtime_capture(capture: RuntimeCapture) -> dict:
    max_rss_mb_after = _max_rss_megabytes()
    return {
        "pid": os.getpid(),
        "started_at": capture.started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "elapsed_ms": round((time.monotonic() - capture.started_monotonic) * 1000.0, 2),
        "max_rss_mb_before": capture.max_rss_mb_before,
        "max_rss_mb_after": max_rss_mb_after,
        "max_rss_delta_mb": round(max_rss_mb_after - capture.max_rss_mb_before, 2),
        "gc_counts_before": list(capture.gc_counts_before),
        "gc_counts_after": list(gc.get_count()),
    }
