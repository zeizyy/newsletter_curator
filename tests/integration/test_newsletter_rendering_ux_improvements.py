from __future__ import annotations

import importlib

from curator.jobs import get_repository_from_config
from tests.fakes import FakeOpenAI
from tests.helpers import create_completed_ingestion_run, write_temp_config


def test_newsletter_rendering_ux_improvements(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["preview@example.com"],
                "digest_subject": "Preview Digest",
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
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    repository.upsert_article_snapshot(
        repository.upsert_story(
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
        ),
        "Rates reset changes software valuations and reprices growth names.",
        summary_headline="Rates reset changes software valuations",
        summary_body=(
            "Key takeaways\n"
            "- Rates reset changes software valuations.\n"
            "- The move is concentrated in long-duration growth names.\n"
            "Why this matters to me\n"
            "This matters for portfolio positioning."
        ),
        summary_model="gpt-5-mini",
        summarized_at="2026-03-21T08:00:00+00:00",
    )
    repository.upsert_article_snapshot(
        repository.upsert_story(
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
        ),
        "Open model pricing changed and pushes buyers to recalculate inference budgets.",
        summary_headline="Open model pricing changed",
        summary_body=(
            "Key takeaways\n"
            "- Open model pricing changed.\n"
            "- The shift changes platform economics.\n"
            "Why this matters to me\n"
            "This matters for inference budgets."
        ),
        summary_model="gpt-5-mini",
        summarized_at="2026-03-21T08:05:00+00:00",
    )

    def fail_live_email_send(*args, **kwargs):
        raise AssertionError("Preview should not send actual email.")

    monkeypatch.setattr(main, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(main, "send_email", fail_live_email_send)

    client = admin_app.app.test_client()
    response = client.get("/preview")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Local Preview" in page
    assert "Freshly Generated" in page
    assert "2 stories selected" in page
    assert "story-source-pill" in page
    assert "Macro Wire" in page
    assert "AI Wire" in page
    assert "Why this matters to me" in page
