from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime, timedelta

from curator.repository import SQLiteRepository
from curator.repository_tools import search_recent_stories
from scripts import backfill_story_search_index
from tests.helpers import create_completed_ingestion_run, write_temp_config


def _config_for(tmp_path) -> tuple[dict, SQLiteRepository]:
    db_path = tmp_path / "curator.sqlite3"
    config = {"database": {"path": str(db_path)}}
    repository = SQLiteRepository(db_path)
    repository.initialize()
    return config, repository


def _seed_story(
    repository: SQLiteRepository,
    *,
    run_id: int,
    subject: str,
    url: str,
    context: str,
    summary_body: str,
    published_at: str,
) -> int:
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Search Wire",
            "subject": subject,
            "url": url,
            "anchor_text": subject,
            "context": context,
            "category": "Tech company news & strategy",
            "published_at": published_at,
            "summary": context,
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        "Article body",
        summary_headline=subject,
        summary_body=summary_body,
        summarized_at=published_at,
    )
    return story_id


def test_search_recent_stories_uses_fts_bm25_ranking(tmp_path):
    config, repository = _config_for(tmp_path)
    run_id = create_completed_ingestion_run(repository, "additional_source")
    now = datetime.now(UTC)

    direct_story_id = _seed_story(
        repository,
        run_id=run_id,
        subject="OpenAI infrastructure capex expands",
        url="https://example.com/openai-infrastructure",
        context="The story is directly about AI infrastructure spending.",
        summary_body="OpenAI is expanding infrastructure capex for model training and inference.",
        published_at=(now - timedelta(minutes=10)).isoformat(),
    )
    _seed_story(
        repository,
        run_id=run_id,
        subject="Cloud budgets tighten",
        url="https://example.com/cloud-budgets",
        context="Capex discipline is becoming more important for cloud buyers.",
        summary_body="Infrastructure teams are watching costs, but the story does not center OpenAI.",
        published_at=(now - timedelta(minutes=5)).isoformat(),
    )

    payload = search_recent_stories(
        config,
        query="OpenAI infrastructure capex",
        window_hours=48,
        source_type=None,
        limit=5,
    )

    assert payload["story_count"] == 2
    assert payload["stories"][0]["id"] == direct_story_id
    assert payload["stories"][0]["summary_body"] == (
        "OpenAI is expanding infrastructure capex for model training and inference."
    )

    source_payload = search_recent_stories(
        config,
        query="Search Wire",
        window_hours=48,
        source_type=None,
        limit=5,
    )
    assert source_payload["story_count"] == 2


def test_story_search_index_backfill_is_idempotent(tmp_path, monkeypatch, capsys):
    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    config = {"database": {"path": str(tmp_path / "curator.sqlite3")}}
    repository = SQLiteRepository(tmp_path / "curator.sqlite3")
    repository.initialize()
    run_id = create_completed_ingestion_run(repository, "additional_source")
    story_id = _seed_story(
        repository,
        run_id=run_id,
        subject="Accelerator demand changes inference economics",
        url="https://example.com/accelerator-demand",
        context="AI teams are reacting to accelerator demand.",
        summary_body="Accelerator demand is changing inference unit economics.",
        published_at=datetime.now(UTC).isoformat(),
    )

    with sqlite3.connect(tmp_path / "curator.sqlite3") as connection:
        connection.execute("DELETE FROM fetched_stories_fts")

    empty_payload = search_recent_stories(
        config,
        query="accelerator demand",
        window_hours=48,
        source_type=None,
        limit=5,
    )
    assert empty_payload["stories"] == []

    monkeypatch.setattr(
        sys,
        "argv",
        ["backfill_story_search_index.py", "--config-path", str(config_path)],
    )
    assert backfill_story_search_index.main() == 0
    assert backfill_story_search_index.main() == 0

    captured = capsys.readouterr()
    assert "1 indexed / 1 stories seen" in captured.out

    payload = search_recent_stories(
        config,
        query="accelerator demand",
        window_hours=48,
        source_type=None,
        limit=5,
    )
    assert payload["story_count"] == 1
    assert payload["stories"][0]["id"] == story_id

    with sqlite3.connect(tmp_path / "curator.sqlite3") as connection:
        fts_count = connection.execute("SELECT COUNT(*) FROM fetched_stories_fts").fetchone()[0]
    assert fts_count == 1
