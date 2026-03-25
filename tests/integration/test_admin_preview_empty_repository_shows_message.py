from __future__ import annotations

import importlib

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
    assert "Live preview generation is disabled in lightweight debug mode." in html
