from __future__ import annotations

import pytest

from curator.config import load_config
from curator.jobs import get_repository_from_config, run_fetch_sources_job
from tests.fakes import FakeArticleFetcher, FakeSourceFetcher
from tests.helpers import write_temp_config


def test_ingest_checkpoints_candidates_before_scoring(monkeypatch, tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "additional_sources": {"enabled": True},
            "limits": {"max_article_chars": 120, "max_fetch_workers": 2},
        },
    )
    config = load_config(str(config_path))

    source_fetcher = FakeSourceFetcher(
        [
            {
                "subject": f"[ai] Story {index}",
                "from": "AI Wire",
                "source_name": "AI Wire",
                "source_type": "additional_source",
                "date": f"2026-03-24T0{index}:00:00+00:00",
                "url": f"https://example.com/ai/story-{index}",
                "anchor_text": f"Story {index}",
                "context": f"Context {index}",
                "category": "AI & ML industry developments",
            }
            for index in range(1, 4)
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            f"https://example.com/ai/story-{index}": (
                f"Story {index} article text with enough detail to summarize deterministically."
            )
            for index in range(1, 4)
        }
    )

    def boom(*args, **kwargs):
        raise RuntimeError("forced scoring failure")

    monkeypatch.setattr("curator.jobs.score_for_ingest", boom)

    with pytest.raises(RuntimeError, match="forced scoring failure"):
        run_fetch_sources_job(
            config,
            source_fetcher=source_fetcher,
            article_fetcher=article_fetcher,
        )

    repository = get_repository_from_config(config)
    stories = repository.list_stories(source_type="additional_source")
    latest_run = repository.get_latest_ingestion_run("additional_source")

    assert len(stories) == 3
    assert all(story["article_text"] for story in stories)
    assert all(not str(story.get("summary_body", "")).strip() for story in stories)
    assert latest_run is not None
    assert latest_run["status"] == "failed"

