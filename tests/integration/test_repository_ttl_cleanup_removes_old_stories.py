from __future__ import annotations

from datetime import UTC, datetime, timedelta

from curator.jobs import get_repository_from_config, run_fetch_sources_job
from tests.helpers import create_completed_ingestion_run, write_temp_config


def test_repository_ttl_cleanup_removes_old_stories(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {
                "path": str(tmp_path / "curator.sqlite3"),
                "ttl_days": 7,
            },
            "additional_sources": {"enabled": True, "hours": 48},
        },
    )

    from curator.config import load_config

    config = load_config(str(config_path))
    repository = get_repository_from_config(config)

    additional_run_id = create_completed_ingestion_run(repository, "additional_source")
    gmail_run_id = create_completed_ingestion_run(repository, "gmail")

    old_timestamp = (datetime.now(UTC) - timedelta(days=9)).isoformat()
    recent_timestamp = (datetime.now(UTC) - timedelta(days=2)).isoformat()

    old_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Old Wire",
            "subject": "Old story",
            "url": "https://example.com/old-story",
            "anchor_text": "Old story",
            "context": "Old context",
            "category": "Tech blogs",
            "published_at": old_timestamp,
        },
        ingestion_run_id=additional_run_id,
    )
    repository.upsert_article_snapshot(old_story_id, "Old article text.")

    old_gmail_story_id = repository.upsert_story(
        {
            "source_type": "gmail",
            "source_name": "Old Mailer <old@example.com>",
            "subject": "Old mail story",
            "url": "https://example.com/old-gmail-story",
            "anchor_text": "Old mail story",
            "context": "Old gmail context",
            "category": "Tech company news & strategy",
            "published_at": old_timestamp,
        },
        ingestion_run_id=gmail_run_id,
    )
    repository.upsert_article_snapshot(old_gmail_story_id, "Old gmail article text.")

    recent_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Fresh Wire",
            "subject": "Recent story",
            "url": "https://example.com/recent-story",
            "anchor_text": "Recent story",
            "context": "Recent context",
            "category": "AI & ML industry developments",
            "published_at": recent_timestamp,
        },
        ingestion_run_id=additional_run_id,
    )
    repository.upsert_article_snapshot(recent_story_id, "Recent article text.")

    def empty_source_fetcher(_config: dict) -> list[dict]:
        return []

    result = run_fetch_sources_job(config, repository=repository, source_fetcher=empty_source_fetcher)

    remaining_stories = repository.list_stories()
    remaining_urls = {story["url"] for story in remaining_stories}
    counts = repository.get_table_counts()

    assert result["status"] == "completed"
    assert result["ttl_cleanup"]["stories_deleted"] == 2
    assert result["ttl_cleanup"]["snapshots_deleted"] == 2
    assert "https://example.com/recent-story" in remaining_urls
    assert "https://example.com/old-story" not in remaining_urls
    assert "https://example.com/old-gmail-story" not in remaining_urls
    assert counts["fetched_stories"] == 1
    assert counts["article_snapshots"] == 1
