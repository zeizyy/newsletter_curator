from __future__ import annotations

import threading
import time

from curator.config import load_config
from curator.jobs import get_repository_from_config, run_fetch_sources_job
from tests.fakes import FakeArticleFetcher, FakeSourceFetcher
from tests.helpers import write_temp_config


def test_fetch_summarization_runs_concurrently(monkeypatch, tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "additional_sources": {"enabled": True},
            "limits": {"max_article_chars": 120, "max_summary_workers": 2},
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
    article_fetcher = FakeArticleFetcher(
        {
            f"https://example.com/ai/story-{index}": (
                f"Story {index} article text with enough detail to summarize deterministically."
            )
            for index in range(1, 5)
        }
    )

    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def fake_summarize_for_ingest(config, article_text, usage_by_model, lock):
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            stats = usage_by_model.setdefault("test-summary-model", {"input": 0, "output": 0, "total": 0})
            stats["input"] += 1
            stats["output"] += 1
            stats["total"] += 2
        with active_lock:
            active -= 1
        headline = article_text.split()[0:3]
        headline_text = " ".join(headline)
        return "{}", headline_text, f"Why this matters to me\n- {headline_text}"

    monkeypatch.setattr("curator.jobs.summarize_for_ingest", fake_summarize_for_ingest)

    config = load_config(str(config_path))
    result = run_fetch_sources_job(
        config,
        source_fetcher=source_fetcher,
        article_fetcher=article_fetcher,
    )

    repository = get_repository_from_config(config)
    stories = repository.list_stories(source_type="additional_source")

    assert result["status"] == "completed"
    assert result["summary_workers"] == 2
    assert max_active == 2
    assert len(stories) == 4
    assert all(story["summary_body"] for story in stories)
