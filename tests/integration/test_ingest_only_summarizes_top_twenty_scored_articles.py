from __future__ import annotations

from curator.config import load_config
from curator.jobs import get_repository_from_config, run_fetch_sources_job
from tests.fakes import FakeArticleFetcher, FakeSourceFetcher
from tests.helpers import write_temp_config


def test_ingest_only_summarizes_top_twenty_scored_articles(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "additional_sources": {"enabled": True},
            "limits": {
                "max_article_chars": 200,
                "max_summary_workers": 4,
                "max_ingest_summaries": 20,
            },
        },
    )
    config = load_config(str(config_path))

    source_fetcher = FakeSourceFetcher(
        [
            {
                "subject": f"[ai] Story {index:02d}",
                "from": "AI Wire",
                "source_name": "AI Wire",
                "source_type": "additional_source",
                "date": f"2026-03-21T{index % 24:02d}:00:00+00:00",
                "url": f"https://example.com/ai/story-{index:02d}",
                "anchor_text": f"Story {index:02d}",
                "context": f"Context for story {index:02d}",
                "category": "AI & ML industry developments",
            }
            for index in range(1, 26)
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            f"https://example.com/ai/story-{index:02d}": (
                f"Story {index:02d} article text with enough detail to summarize deterministically."
            )
            for index in range(1, 26)
        }
    )

    result = run_fetch_sources_job(
        config,
        source_fetcher=source_fetcher,
        article_fetcher=article_fetcher,
    )
    repository = get_repository_from_config(config)
    stories = repository.list_stories(source_type="additional_source")

    assert result["status"] == "completed"
    assert result["stories_seen"] == 25
    assert result["scored_candidates"] == 25
    assert result["summary_candidates"] == 20
    assert result["summary_workers"] == 4
    assert result["stories_persisted"] == 20
    assert result["snapshots_persisted"] == 20
    assert len(stories) == 20
    assert all(str(story.get("summary_body", "")).strip() for story in stories)
    assert result["usage_by_model"][config["openai"]["reasoning_model"]]["total"] > 0
    assert result["usage_by_model"][config["openai"]["summary_model"]]["total"] >= 40
