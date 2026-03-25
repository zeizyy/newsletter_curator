from __future__ import annotations

import importlib
from datetime import UTC, datetime

from curator.jobs import get_repository_from_config, run_newsletter_ttl_cleanup
from tests.helpers import write_temp_config


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 22, 18, 0, 0, tzinfo=tz or UTC)


def test_newsletter_history_view_and_ttl(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")
    jobs = importlib.import_module("curator.jobs")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {
                "path": str(tmp_path / "curator.sqlite3"),
                "ttl_days": 7,
                "newsletter_ttl_days": 2,
            }
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)

    config = main.load_config()
    repository = get_repository_from_config(config)

    old_newsletter_id = repository.upsert_daily_newsletter(
        newsletter_date="2026-03-20",
        subject="Old Digest",
        body="Old digest body",
        html_body="<div>Old digest body</div>",
        selected_items=[{"title": "Old Story", "url": "https://example.com/old"}],
    )
    recent_newsletter_id = repository.upsert_daily_newsletter(
        newsletter_date="2026-03-21",
        subject="Recent Digest",
        body="Recent digest body",
        html_body="<div>Recent digest body</div>",
        selected_items=[{"title": "Recent Story", "url": "https://example.com/recent"}],
    )
    repository.upsert_daily_newsletter(
        newsletter_date="2026-03-22",
        subject="Today Digest",
        body="Today digest body",
        html_body="<div>Today digest body</div>",
        selected_items=[{"title": "Today Story", "url": "https://example.com/today"}],
    )

    open_token = repository.ensure_newsletter_open_token(old_newsletter_id)
    tracked_links = repository.ensure_tracked_links(
        old_newsletter_id,
        [{"title": "Old Story", "url": "https://example.com/old"}],
    )
    repository.record_newsletter_open(open_token, user_agent="test-agent", ip_address="1.1.1.1")
    repository.record_newsletter_click(
        str(tracked_links[0]["click_token"]),
        user_agent="test-agent",
        ip_address="1.1.1.1",
    )

    repository.acquire_preview_generation("2026-03-20")

    cleanup = run_newsletter_ttl_cleanup(config, repository)
    counts = repository.get_table_counts()

    assert cleanup["ttl_days"] == 2
    assert cleanup["cutoff_newsletter_date"] == "2026-03-21"
    assert cleanup["newsletters_deleted"] == 1
    assert cleanup["preview_generations_deleted"] == 1
    assert cleanup["telemetry_deleted"] == 1
    assert cleanup["tracked_links_deleted"] == 1
    assert cleanup["open_events_deleted"] == 1
    assert cleanup["click_events_deleted"] == 1
    assert counts["daily_newsletters"] == 2
    assert counts["newsletter_telemetry"] == 0
    assert counts["tracked_links"] == 0
    assert counts["newsletter_open_events"] == 0
    assert counts["newsletter_click_events"] == 0
    assert repository.get_daily_newsletter("2026-03-20") is None
    assert repository.get_daily_newsletter("2026-03-21") is not None

    client = admin_app.app.test_client()

    history_response = client.get("/newsletters")
    assert history_response.status_code == 200
    history_page = history_response.get_data(as_text=True)
    assert "Archive Ledger" in history_page
    assert "Command Rail" in history_page
    assert "Today Digest" in history_page
    assert "Recent Digest" in history_page
    assert "Old Digest" not in history_page

    detail_response = client.get("/newsletters/2026-03-21")
    assert detail_response.status_code == 200
    detail_page = detail_response.get_data(as_text=True)
    assert "Recent Digest" in detail_page
    assert "Recent digest body" in detail_page
    assert "Back To History" in detail_page
    assert "Stored Newsletter" in detail_page
