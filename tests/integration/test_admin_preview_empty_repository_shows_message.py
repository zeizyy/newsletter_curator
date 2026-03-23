from __future__ import annotations

import importlib

from curator.jobs import current_newsletter_date, get_repository_from_config
from tests.helpers import write_temp_config


def test_admin_preview_empty_repository_shows_message(monkeypatch, tmp_path):
    main = importlib.import_module("main")
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
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))

    def fail_preview_job(_config: dict):
        raise AssertionError("preview_job should not run when the repository is empty.")

    monkeypatch.setattr(admin_app, "preview_job", fail_preview_job)

    repository = get_repository_from_config(main.load_config())
    assert repository.get_daily_newsletter(current_newsletter_date()) is None

    client = admin_app.app.test_client()
    response = client.get("/preview")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No delivery-ready stories are available yet" in html
    assert "Run the fetch job to populate the repository" in html
    assert repository.get_preview_generation(current_newsletter_date()) is None
