from __future__ import annotations

import threading
import time

from curator.config import load_config
from curator.jobs import run_fetch_sources_job
from tests.fakes import FakeSourceFetcher
from tests.helpers import write_temp_config


def test_fetch_article_collection_runs_concurrently(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "additional_sources": {"enabled": True},
            "limits": {
                "max_article_chars": 120,
                "max_fetch_workers": 2,
                "max_summary_workers": 1,
            },
        },
    )
    source_fetcher = FakeSourceFetcher(
        [
            {
                "subject": f"[ai] Story {index}",
                "from": "AI Wire",
                "source_name": "AI Wire",
                "source_type": "additional_source",
                "date": f"2026-03-21T0{index}:00:00+00:00",
                "url": f"https://example.com/ai/story-{index}",
                "anchor_text": f"Story {index}",
                "context": f"Context {index}",
                "category": "AI & ML industry developments",
            }
            for index in range(1, 5)
        ]
    )

    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def article_fetcher(url: str, max_article_chars: int, timeout: int = 15, retries: int = 2):
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with active_lock:
            active -= 1
        return {
            "article_text": f"{url} article text with enough detail to summarize.",
            "document_title": "Fetched title",
            "document_excerpt": "Fetched excerpt",
        }

    config = load_config(str(config_path))
    result = run_fetch_sources_job(
        config,
        source_fetcher=source_fetcher,
        article_fetcher=article_fetcher,
    )

    assert result["status"] == "completed"
    assert max_active == 2

