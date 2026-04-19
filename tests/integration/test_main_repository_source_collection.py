from __future__ import annotations

import importlib
from datetime import UTC, datetime

from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run, write_temp_config


def test_main_collect_additional_source_links_uses_configured_repo_root(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")
    sources = importlib.import_module("curator.sources")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": "data/newsletter_curator.sqlite3"},
            "additional_sources": {"enabled": True, "hours": 48},
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(main.config_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(jobs, "BASE_DIR", tmp_path)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 4, 19, 13, 0, 0, tzinfo=tz or UTC)

    monkeypatch.setattr(sources, "datetime", FixedDateTime)

    config = main.load_config()
    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "OpenAI News",
            "subject": "[ai] Model release",
            "url": "https://example.com/model-release",
            "anchor_text": "Model release",
            "context": "Repository context for model release",
            "category": "ai",
            "published_at": "2026-04-19T12:00:00+00:00",
            "summary": "Model release summary",
        },
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        "Model release article text.",
        summary_headline="Model release",
        summary_body="Model release summary.",
        summary_model="gpt-5-mini",
        summarized_at="2026-04-19T12:05:00+00:00",
    )

    links = main.collect_additional_source_links(config)

    assert [link["url"] for link in links] == ["https://example.com/model-release"]
