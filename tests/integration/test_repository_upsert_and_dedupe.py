from __future__ import annotations

from curator.repository import SQLiteRepository, canonicalize_url
from tests.helpers import temp_db_path


def test_repository_upsert_and_dedupe(tmp_path):
    repository = SQLiteRepository(temp_db_path(tmp_path))
    repository.initialize()

    ingestion_run_id = repository.create_ingestion_run(
        "additional_source", metadata={"mode": "integration"}
    )
    delivery_run_id = repository.create_delivery_run(metadata={"mode": "integration"})

    duplicate_story = {
        "source_type": "additional_source",
        "source_name": "AI Wire",
        "subject": "[ai] Open model pricing changed",
        "url": "https://example.com/ai/model-pricing?utm_source=newsletter",
        "anchor_text": "Open model pricing changed",
        "context": "First ingest context",
        "category": "AI & ML industry developments",
        "published_at": "2026-03-21T06:00:00+00:00",
        "summary": "First summary",
    }
    second_story = {
        "source_type": "additional_source",
        "source_name": "Macro Wire",
        "subject": "[markets] Rates reset",
        "url": "https://example.com/markets/rates-reset",
        "anchor_text": "Rates reset changes software valuations",
        "context": "Rates reset context",
        "category": "Markets / stocks / macro / economy",
        "published_at": "2026-03-21T07:30:00+00:00",
        "summary": "Second summary",
    }

    first_story_id = repository.upsert_story(duplicate_story, ingestion_run_id=ingestion_run_id)
    repository.upsert_article_snapshot(first_story_id, "Initial article text")

    updated_duplicate = dict(duplicate_story)
    updated_duplicate["url"] = "https://example.com/ai/model-pricing?utm_source=other&utm_campaign=test"
    updated_duplicate["context"] = "Updated context after reingest"
    updated_duplicate["summary"] = "Updated summary"
    duplicate_story_id = repository.upsert_story(updated_duplicate, ingestion_run_id=ingestion_run_id)
    repository.upsert_article_snapshot(duplicate_story_id, "Updated article text")

    second_story_id = repository.upsert_story(second_story, ingestion_run_id=ingestion_run_id)
    repository.upsert_article_snapshot(second_story_id, "Rates article text")

    repository.complete_ingestion_run(
        ingestion_run_id,
        status="completed",
        metadata={"stories_seen": 3, "stories_persisted": 2},
    )
    repository.complete_delivery_run(
        delivery_run_id,
        status="completed",
        metadata={"stories_delivered": 2},
    )
    repository.set_source_selection(
        source_type="additional_source", source_name="AI Wire", enabled=True
    )

    counts = repository.get_table_counts()
    assert counts["schema_migrations"] == 3
    assert counts["sources"] == 2
    assert counts["ingestion_runs"] == 1
    assert counts["delivery_runs"] == 1
    assert counts["fetched_stories"] == 2
    assert counts["article_snapshots"] == 2
    assert counts["user_source_selections"] == 1

    assert first_story_id == duplicate_story_id
    all_stories = repository.list_stories(source_type="additional_source")
    assert len(all_stories) == 2
    assert all_stories[0]["source_name"] == "Macro Wire"
    assert all_stories[1]["source_name"] == "AI Wire"
    assert all_stories[1]["context"] == "Updated context after reingest"
    assert all_stories[1]["article_text"] == "Updated article text"
    assert all_stories[1]["canonical_url"] == canonicalize_url(duplicate_story["url"])

    ai_stories = repository.list_stories(
        source_type="additional_source",
        source_name="AI Wire",
        published_after="2026-03-21T00:00:00+00:00",
    )
    assert len(ai_stories) == 1
    assert ai_stories[0]["summary"] == "Updated summary"

    enabled_sources = repository.list_enabled_sources()
    assert enabled_sources == [
        {"source_type": "additional_source", "source_name": "AI Wire", "enabled": True},
        {"source_type": "additional_source", "source_name": "Macro Wire", "enabled": True},
    ]
