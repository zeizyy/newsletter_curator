from __future__ import annotations

from curator.content import ACCESS_CLASSIFIER_VERSION
from curator.jobs import get_repository_from_config, run_fetch_sources_job
from tests.fakes import FakeArticleFetcher, FakeSourceFetcher
from tests.helpers import write_temp_config


def test_ingest_persists_servability_metadata(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "additional_sources": {"enabled": True, "hours": 24},
            "limits": {
                "max_ingest_summaries": 1,
                "select_top_stories": 1,
                "final_top_stories": 1,
                "source_quotas": {"gmail": 0, "additional_source": 1},
            },
        },
    )

    from curator.config import load_config

    config = load_config(str(config_path))
    source_fetcher = FakeSourceFetcher(
        [
            {
                "subject": "[markets] First public article",
                "from": "Open Wire",
                "source_name": "Open Wire",
                "source_type": "additional_source",
                "date": "2026-03-21T07:30:00+00:00",
                "url": "https://example.com/markets/first-public",
                "anchor_text": "First public article",
                "context": "First public article context",
                "category": "Markets / stocks / macro / economy",
            },
            {
                "subject": "[ai] Second public article",
                "from": "Open Wire",
                "source_name": "Open Wire",
                "source_type": "additional_source",
                "date": "2026-03-21T06:30:00+00:00",
                "url": "https://example.com/ai/second-public",
                "anchor_text": "Second public article",
                "context": "Second public article context",
                "category": "AI & ML industry developments",
            },
            {
                "subject": "[media] Subscriber wall",
                "from": "Locked Wire",
                "source_name": "Locked Wire",
                "source_type": "additional_source",
                "date": "2026-03-21T05:30:00+00:00",
                "url": "https://example.com/media/subscriber-wall",
                "anchor_text": "Subscriber wall",
                "context": "Subscriber wall context",
                "category": "Tech blogs",
            },
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            "https://example.com/markets/first-public": (
                "First public article text with enough detail to support a summary."
            ),
            "https://example.com/ai/second-public": (
                "Second public article text that should persist without a summary."
            ),
            "https://example.com/media/subscriber-wall": (
                "Subscribe to continue reading. Already a subscriber? Sign in to continue reading."
            ),
        }
    )

    fetch_result = run_fetch_sources_job(
        config,
        source_fetcher=source_fetcher,
        article_fetcher=article_fetcher,
    )
    repository = get_repository_from_config(config)
    stories = repository.list_stories(source_type="additional_source")

    assert fetch_result["status"] == "completed"
    assert fetch_result["stories_persisted"] == 3
    assert len(stories) == 3

    by_url = {story["url"]: story for story in stories}
    servable = by_url["https://example.com/markets/first-public"]
    candidate = by_url["https://example.com/ai/second-public"]
    blocked = by_url["https://example.com/media/subscriber-wall"]

    assert servable["servability_status"] == "servable"
    assert servable["detector_version"] == ACCESS_CLASSIFIER_VERSION
    assert servable["classifier_signals"]["word_count"] > 0
    assert servable["summary_body"]

    assert candidate["servability_status"] == "candidate"
    assert candidate["detector_version"] == ACCESS_CLASSIFIER_VERSION
    assert candidate["classifier_signals"]["word_count"] > 0
    assert candidate["summary_body"] == ""

    assert blocked["servability_status"] == "blocked"
    assert blocked["detector_version"] == ACCESS_CLASSIFIER_VERSION
    assert blocked["paywall_detected"] == 1
    assert blocked["paywall_reason"] == "subscribe_to_continue"
    assert "subscribe_to_continue" in blocked["classifier_signals"]["strong_text_markers"]
