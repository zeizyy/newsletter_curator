from __future__ import annotations

import importlib

from curator.jobs import get_repository_from_config
from tests.fakes import FakeOpenAI
from tests.helpers import create_completed_ingestion_run, write_temp_config


def test_selected_theme_renders_newsletter_digest_with_story_count_and_dark_mode(monkeypatch, tmp_path):
    main = importlib.import_module("main")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["preview@example.com"],
                "digest_subject": "Theme Digest",
            },
            "additional_sources": {"enabled": True, "hours": 48},
            "limits": {
                "select_top_stories": 2,
                "final_top_stories": 2,
                "source_quotas": {"gmail": 0, "additional_source": 2},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")

    first_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Macro Wire",
            "subject": "[markets] Rates reset",
            "url": "https://example.com/markets/rates-reset",
            "anchor_text": "Rates reset changes software valuations",
            "context": "Repository context for rates reset",
            "category": "Markets / stocks / macro / economy",
            "published_at": "2026-03-21T07:30:00+00:00",
            "summary": "Rates reset summary",
        },
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_article_snapshot(
        first_story_id,
        "Rates reset changes software valuations and reprices growth names.",
        summary_headline="Rates reset changes software valuations",
        summary_body="Key takeaways\n- Rates reset changes software valuations.\n\nWhy this matters to me\nThis matters for software multiples.",
        summary_model="gpt-5-mini",
        summarized_at="2026-03-21T08:00:00+00:00",
    )

    second_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "AI Wire",
            "subject": "[ai] Open model pricing changed",
            "url": "https://example.com/ai/model-pricing",
            "anchor_text": "Open model pricing changed",
            "context": "Repository context for pricing",
            "category": "AI & ML industry developments",
            "published_at": "2026-03-21T06:00:00+00:00",
            "summary": "Pricing summary",
        },
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_article_snapshot(
        second_story_id,
        "Open model pricing changed and pushes buyers to recalculate inference budgets.",
        summary_headline="Open model pricing changed",
        summary_body="Key takeaways\n- Open model pricing changed.\n\nWhy this matters to me\nThis matters for inference budgets.",
        summary_model="gpt-5-mini",
        summarized_at="2026-03-21T08:05:00+00:00",
    )

    fake_openai = FakeOpenAI()
    monkeypatch.setattr(main, "OpenAI", lambda: fake_openai)

    result = main.preview_job(config)

    assert result["status"] == "completed"
    assert result["preview"] is not None
    html = result["preview"]["html_body"]
    assert "Newsletter Digest" in html
    assert "The highest-signal stories for today, pre-ranked and condensed for fast scanning." in html
    assert "2 stories selected" in html
    assert "Read original" in html
    assert 'target="_blank"' in html
    assert "Mar 21, 12:30 AM PT" in html
    assert 'data-story-timestamp="' in html
    assert "Financial Times" not in html
    assert "@media (prefers-color-scheme: dark)" in html
    assert "[data-ogsc]" in html
    assert "story-time" in html
