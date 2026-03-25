from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run
from tests.helpers import write_temp_config


def test_admin_preview_disabled_by_default_shows_message(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "additional_sources": {"enabled": True},
            "limits": {"source_quotas": {"gmail": 0, "additional_source": 5}},
            "email": {"digest_recipients": ["preview@example.com"]},
        },
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))

    def fail_preview_job(_config: dict):
        raise AssertionError("run_preview_job should not run when preview generation is disabled.")

    monkeypatch.setattr(admin_app, "run_preview_job", fail_preview_job)

    client = admin_app.app.test_client()
    response = client.get("/preview")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Preview unavailable right now" in html
    assert "Live preview generation is disabled in lightweight debug mode." in html
    assert "Open Control Room" in html
    assert "Open Archive" in html


def test_admin_preview_loading_state_uses_editorial_shell(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "additional_sources": {"enabled": True, "hours": 48},
            "limits": {
                "select_top_stories": 1,
                "final_top_stories": 1,
                "source_quotas": {"gmail": 0, "additional_source": 1},
            },
            "email": {"digest_recipients": ["preview@example.com"]},
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CURATOR_ADMIN_ENABLE_PREVIEW", "1")

    config = main.load_config()
    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    published_at = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Macro Wire",
            "subject": "[markets] Rates reset",
            "url": "https://example.com/markets/rates-reset",
            "anchor_text": "Rates reset changes software valuations",
            "context": "Repository context for rates reset",
            "category": "Markets / stocks / macro / economy",
            "published_at": published_at,
            "summary": "Rates reset summary",
        },
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        "Rates reset changes software valuations and reprices growth.",
        summary_headline="Rates reset changes software valuations",
        summary_body="Key takeaways\n- Rates reset changes software valuations.",
        summary_model="gpt-5-mini",
        summarized_at=(datetime.now(UTC) - timedelta(hours=1, minutes=55)).isoformat(),
    )
    repository.acquire_preview_generation(admin_app.current_newsletter_date())

    client = admin_app.app.test_client()
    response = client.get("/preview")
    html = response.get_data(as_text=True)

    assert response.status_code == 202
    assert "Stand by for the next refresh" in html
    assert "Auto refresh on" in html
    assert "Open Control Room" in html
