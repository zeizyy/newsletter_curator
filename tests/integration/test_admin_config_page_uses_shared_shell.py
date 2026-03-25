from __future__ import annotations

import importlib

from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run, write_temp_config


def test_admin_config_page_uses_shared_shell(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["ops@example.com", "desk@example.com"],
                "digest_subject": "Desk Digest",
            },
            "additional_sources": {"enabled": True},
            "persona": {"text": "Focus on pricing power and distribution shifts."},
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Macro Wire",
            "subject": "[markets] Rates reset",
            "url": "https://example.com/markets/rates-reset",
            "anchor_text": "Rates reset changes software valuations",
            "context": "Repository context for rates reset",
            "category": "Markets / stocks / macro / economy",
        },
        ingestion_run_id=ingestion_run_id,
    )

    client = admin_app.app.test_client()
    response = client.get("/")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Control Room" in page
    assert "Operations Console" in page
    assert "Operational Snapshot" in page
    assert "Command Rail" in page
    assert "Repository source selection" in page
    assert "Macro Wire" in page
    assert "Save Config" in page
