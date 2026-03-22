from __future__ import annotations

import importlib

from curator.jobs import get_repository_from_config
from tests.fakes import FakeOpenAI
from tests.helpers import create_completed_ingestion_run, write_temp_config


def test_admin_preview_renders_digest(monkeypatch, tmp_path):
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
    )

    def fail_live_email_send(*args, **kwargs):
        raise AssertionError("Preview should not send actual email.")

    monkeypatch.setattr(main, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(main, "send_email", fail_live_email_send)

    client = admin_app.app.test_client()
    response = client.get("/preview")
    assert response.status_code == 202
    assert "generation has started" in response.get_data(as_text=True).lower()

    for _ in range(20):
        response = client.get("/preview")
        if response.status_code == 200:
            break

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Newsletter Preview" in page
    assert "Preview Digest" in page
    assert "Market Tape Preview" in page
    assert "Rates reset changes software valuations" in page
    assert "Open model pricing changed" in page
    assert "Read original" in page
    assert 'target="_blank"' in page
    assert "Mar 21, 12:30 AM PT" in page
    assert "data-story-timestamp" in page
    assert "Intl.DateTimeFormat" in page
