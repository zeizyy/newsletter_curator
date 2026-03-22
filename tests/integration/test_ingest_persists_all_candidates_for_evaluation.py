from __future__ import annotations

from curator.config import load_config
from curator.jobs import get_repository_from_config, run_fetch_sources_job
from tests.fakes import FakeArticleFetcher, FakeSourceFetcher
from tests.helpers import write_temp_config


def test_ingest_persists_all_candidates_for_evaluation(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "additional_sources": {"enabled": True},
            "limits": {
                "max_article_chars": 200,
                "max_summary_workers": 3,
                "max_ingest_summaries": 2,
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
            for index in range(1, 5)
        ]
        + [
            {
                "subject": "[media] Paywalled Story",
                "from": "Locked Wire",
                "source_name": "Locked Wire",
                "source_type": "additional_source",
                "date": "2026-03-21T07:30:00+00:00",
                "url": "https://example.com/media/paywalled-story",
                "anchor_text": "Paywalled Story",
                "context": "Paywalled context",
                "category": "Tech blogs",
            }
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            **{
                f"https://example.com/ai/story-{index:02d}": (
                    f"Story {index:02d} article text with enough detail to summarize deterministically."
                )
                for index in range(1, 5)
            },
            "https://example.com/media/paywalled-story": (
                "Subscribe to continue reading. Already a subscriber? Sign in to continue reading."
            ),
        }
    )

    result = run_fetch_sources_job(
        config,
        source_fetcher=source_fetcher,
        article_fetcher=article_fetcher,
    )
    repository = get_repository_from_config(config)
    stories = repository.list_stories(source_type="additional_source")
    servable = repository.list_stories(
        source_type="additional_source",
        include_paywalled=False,
        require_summary=True,
    )

    assert result["status"] == "completed"
    assert result["stories_seen"] == 5
    assert result["summary_candidates"] == 2
    assert result["paywall_stories"] == 1
    assert result["stories_persisted"] == 5
    assert result["snapshots_persisted"] == 5
    assert len(stories) == 5
    assert len(servable) == 2
    assert sum(1 for story in stories if str(story.get("summary_body", "")).strip()) == 2

    paywalled = next(story for story in stories if story["source_name"] == "Locked Wire")
    assert paywalled["paywall_detected"] == 1
    assert str(paywalled.get("summary_body", "")).strip() == ""

    unsummarized = [
        story
        for story in stories
        if story["source_name"] == "AI Wire" and not str(story.get("summary_body", "")).strip()
    ]
    assert len(unsummarized) == 2
