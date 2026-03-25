from __future__ import annotations

import importlib

from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run, write_temp_config


def test_admin_story_explorer_lists_repository_stories(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "additional_sources": {"enabled": True, "hours": 48},
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    repository = get_repository_from_config(config)
    additional_run_id = create_completed_ingestion_run(repository, "additional_source")
    gmail_run_id = create_completed_ingestion_run(repository, "gmail")

    macro_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Macro Wire",
            "subject": "[markets] Rates reset",
            "url": "https://example.com/markets/rates-reset",
            "anchor_text": "Rates reset changes software valuations",
            "context": "Repository context for rates reset",
            "category": "Markets / stocks / macro / economy",
            "published_at": "2026-03-21T07:30:00+00:00",
        },
        ingestion_run_id=additional_run_id,
    )
    repository.upsert_article_snapshot(
        macro_story_id,
        "Rates reset changes software valuations and reprices growth.",
    )
    repository.upsert_story(
        {
            "source_type": "gmail",
            "source_name": "Infra Letter <infra@example.com>",
            "subject": "Cloud budgets reset",
            "url": "https://example.com/gmail/cloud-budgets",
            "anchor_text": "Cloud budgets reset",
            "context": "Cloud budgets context",
            "category": "Tech company news & strategy",
            "published_at": "2026-03-21T06:30:00+00:00",
        },
        ingestion_run_id=gmail_run_id,
    )

    client = admin_app.app.test_client()

    response = client.get("/stories")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Signal Repository" in page
    assert "Repository Inventory" in page
    assert "Command Rail" in page
    assert "Rates reset changes software valuations" in page
    assert "Cloud budgets reset" in page
    assert "Infra Letter" in page
    assert "infra@example.com" not in page
    assert "snapshot stored" in page
    assert "metadata only" in page

    filtered_response = client.get("/stories?source_type=additional_source&source_name=Macro")
    assert filtered_response.status_code == 200
    filtered_page = filtered_response.get_data(as_text=True)
    assert "Rates reset changes software valuations" in filtered_page
    assert "Cloud budgets reset" not in filtered_page
