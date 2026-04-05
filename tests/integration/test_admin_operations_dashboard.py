from __future__ import annotations

import datetime as dt
import importlib

from curator.jobs import get_repository_from_config
from tests.helpers import write_temp_config


def test_admin_operations_dashboard(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    credentials_path = tmp_path / "credentials.json"
    token_path = tmp_path / "token.json"
    credentials_path.write_text("{}", encoding="utf-8")
    token_path.write_text("{}", encoding="utf-8")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "paths": {
                "credentials": str(credentials_path),
                "token": str(token_path),
            },
            "additional_sources": {"enabled": True, "hours": 24},
            "tracking": {"enabled": True, "base_url": "https://tracking.example.com"},
        },
    )
    monkeypatch.setenv("CURATOR_PUBLIC_BASE_URL", "https://subscriber.example.com")
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))

    config = main.load_config()
    repository = get_repository_from_config(config)

    for source_type in ("gmail", "additional_source"):
        run_id = repository.create_ingestion_run(source_type, metadata={"job": f"fetch_{source_type}"})
        repository.complete_ingestion_run(run_id, status="completed", metadata={"job": f"fetch_{source_type}"})

    older_delivery_run_ids: list[int] = []
    for offset in range(10, 0, -1):
        run_id = repository.create_delivery_run(metadata={"job": "deliver_digest"})
        older_delivery_run_ids.append(run_id)
        repository.complete_delivery_run(
            run_id,
            status="completed",
            metadata={
                "job": "deliver_digest",
                "newsletter_date": (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=offset + 2)).isoformat(),
                "pipeline_result": {
                    "sent_recipients": offset,
                    "failed_recipient_count": 0,
                    "recipient_source": "buttondown",
                    "audience_key": "default",
                },
            },
        )

    completed_delivery_run_id = repository.create_delivery_run(metadata={"job": "deliver_digest"})
    repository.complete_delivery_run(
        completed_delivery_run_id,
        status="completed",
        metadata={
            "job": "deliver_digest",
            "newsletter_date": (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=1)).isoformat(),
            "pipeline_result": {
                "sent_recipients": 24,
                "failed_recipient_count": 0,
                "recipient_source": "buttondown",
                "audience_key": "default",
            },
        },
    )

    failed_delivery_run_id = repository.create_delivery_run(metadata={"job": "deliver_digest"})
    repository.complete_delivery_run(
        failed_delivery_run_id,
        status="failed",
        metadata={
            "job": "deliver_digest",
            "newsletter_date": dt.datetime.now(dt.UTC).date().isoformat(),
            "pipeline_result": {
                "sent_recipients": 0,
                "failed_recipient_count": 3,
                "recipient_source": "buttondown",
                "audience_key": "default",
            },
        },
    )

    client = admin_app.app.test_client()
    response = client.get("/operations")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Operations Deck" in html
    assert "SQLite Connectivity" in html
    assert "Config Validity" in html
    assert "Gmail Auth Presence" in html
    assert "Public Base URL Consistency" in html
    assert "Last Successful Ingest" in html
    assert "Last Successful Delivery" in html
    assert "Daily Delivery Status" in html
    assert "Mismatch between tracking base URL and subscriber public base URL." in html
    assert "tracking.example.com" in html
    assert "subscriber.example.com" in html
    assert "buttondown" in html
    assert "24 sent" in html
    assert "3 failed" in html
    assert "completed" in html
    assert "failed" in html
    assert html.index("Recent delivery runs") < html.index("Runtime health")
    assert html.count('<div class="muted">run #') == 10
    assert f'<div class="muted">run #{older_delivery_run_ids[0]}</div>' not in html
    assert f'<div class="muted">run #{older_delivery_run_ids[1]}</div>' not in html
    assert f'<div class="muted">run #{completed_delivery_run_id}</div>' in html
    assert f'<div class="muted">run #{failed_delivery_run_id}</div>' in html
