from __future__ import annotations

import importlib
from datetime import UTC, datetime

from curator.jobs import get_repository_from_config, run_newsletter_ttl_cleanup
from tests.helpers import create_completed_ingestion_run, write_temp_config


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
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    recent_delivery_run_id = repository.create_delivery_run(metadata={"job": "deliver_digest"})
    repository.complete_delivery_run(
        recent_delivery_run_id,
        status="completed",
        metadata={
            "pipeline_result": {
                "gmail_links": 4,
                "additional_source_links": 6,
                "eligible_links": 9,
                "processed_candidates": 3,
            }
        },
    )

    old_newsletter_id = repository.upsert_daily_newsletter(
        newsletter_date="2026-03-20",
        subject="Old Digest",
        body="Old digest body",
        html_body="<div>Old digest body</div>",
        selected_items=[{"title": "Old Story", "url": "https://example.com/old"}],
    )
    recent_newsletter_id = repository.upsert_daily_newsletter(
        newsletter_date="2026-03-21",
        delivery_run_id=recent_delivery_run_id,
        subject="Recent Digest",
        body="Recent digest body",
        html_body="<div>Recent digest body</div>",
        selected_items=[{"title": "Recent Story", "url": "https://example.com/recent"}],
        metadata={
            "accepted_items": 1,
        },
    )
    repository.upsert_daily_newsletter(
        newsletter_date="2026-03-22",
        subject="Today Digest",
        body="Today digest body",
        html_body="<div>Today digest body</div>",
        selected_items=[{"title": "Today Story", "url": "https://example.com/today"}],
        metadata={
            "gmail_links": 5,
            "additional_source_links": 7,
            "eligible_links": 11,
            "processed_candidates": 2,
            "accepted_items": 1,
        },
    )
    story_id = repository.upsert_story(
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
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        "Rates reset changes software valuations and reprices growth.",
    )
    repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Macro Wire",
            "subject": "[ai] Semis supply",
            "url": "https://example.com/markets/semis-supply",
            "anchor_text": "Semis supply improves for AI servers",
            "context": "Repository context for semis supply",
            "category": "AI infrastructure",
            "published_at": "2026-03-21T11:15:00+00:00",
        },
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Macro Wire",
            "subject": "[markets] Credit spreads",
            "url": "https://example.com/markets/credit-spreads",
            "anchor_text": "Credit spreads widen into earnings",
            "context": "Repository context for credit spreads",
            "category": "Markets / stocks / macro / economy",
            "published_at": "2026-03-20T20:45:00+00:00",
        },
        ingestion_run_id=ingestion_run_id,
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
    assert "Archive" in history_page
    assert "Command Rail" in history_page
    assert "Today Digest" in history_page
    assert "Recent Digest" in history_page
    assert "sourced=11" in history_page
    assert "gmail=5" in history_page
    assert "additional=7" in history_page
    assert "processed=2" in history_page
    assert "selected=1" in history_page
    assert "Old Digest" not in history_page
    assert 'data-label="Subject"' in history_page
    assert "Inventory" in history_page
    assert "Current repository inventory" not in history_page
    assert "Rates reset changes software valuations" not in history_page
    assert "Credit spreads widen into earnings" not in history_page

    inventory_response = client.get("/inventory")
    assert inventory_response.status_code == 200
    inventory_page = inventory_response.get_data(as_text=True)
    assert "Inventory" in inventory_page
    assert "Current repository inventory" in inventory_page
    assert "Showing 2 of 3 repository stories for 2026-03-21." in inventory_page
    assert "All Days" in inventory_page
    assert "2026-03-21 &middot; 2" in inventory_page
    assert "2026-03-20 &middot; 1" in inventory_page
    assert "Rates reset changes software valuations" in inventory_page
    assert "Semis supply improves for AI servers" in inventory_page
    assert "Credit spreads widen into earnings" not in inventory_page

    older_inventory_response = client.get("/inventory?inventory_day=2026-03-20")
    assert older_inventory_response.status_code == 200
    older_inventory_page = older_inventory_response.get_data(as_text=True)
    assert "Showing 1 of 3 repository stories for 2026-03-20." in older_inventory_page
    assert "Credit spreads widen into earnings" in older_inventory_page
    assert "Rates reset changes software valuations" not in older_inventory_page

    all_inventory_response = client.get("/inventory?inventory_day=all")
    assert all_inventory_response.status_code == 200
    all_inventory_page = all_inventory_response.get_data(as_text=True)
    assert "Showing all 3 repository stories." in all_inventory_page
    assert "Rates reset changes software valuations" in all_inventory_page
    assert "Credit spreads widen into earnings" in all_inventory_page

    detail_response = client.get("/newsletters/2026-03-21")
    assert detail_response.status_code == 200
    detail_page = detail_response.get_data(as_text=True)
    assert "Recent Digest" in detail_page
    assert "Recent digest body" in detail_page
    assert "Gmail 4" in detail_page
    assert "additional 6" in detail_page
    assert "after initial ranking" in detail_page
    assert "Back To History" in detail_page
    assert "Archive" in detail_page


def test_newsletter_history_empty_state_uses_editorial_shell(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))

    client = admin_app.app.test_client()
    response = client.get("/newsletters")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No stored newsletters yet" in html
    assert "Open Control Room" in html

    inventory_response = client.get("/inventory")
    inventory_html = inventory_response.get_data(as_text=True)

    assert inventory_response.status_code == 200
    assert "No active stories yet" in inventory_html
    assert "Open Archive" in inventory_html


def test_newsletter_history_shows_one_generated_newsletter_per_day_across_audiences(
    monkeypatch,
    tmp_path,
):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))

    config = main.load_config()
    repository = get_repository_from_config(config)
    repository.upsert_daily_newsletter(
        newsletter_date="2026-03-23",
        audience_key="personalized-a",
        subject="Personalized Only Digest",
        body="Personalized only body",
        html_body="<div>Personalized only body</div>",
        selected_items=[{"title": "Personalized Story", "url": "https://example.com/p"}],
    )
    repository.upsert_daily_newsletter(
        newsletter_date="2026-03-24",
        audience_key="personalized-b",
        subject="Personalized Variant Digest",
        body="Personalized variant body",
        html_body="<div>Personalized variant body</div>",
        selected_items=[{"title": "Personalized Variant", "url": "https://example.com/v"}],
    )
    repository.upsert_daily_newsletter(
        newsletter_date="2026-03-24",
        subject="Default Digest",
        body="Default body",
        html_body="<div>Default body</div>",
        selected_items=[{"title": "Default Story", "url": "https://example.com/d"}],
    )

    client = admin_app.app.test_client()

    history_response = client.get("/newsletters")
    assert history_response.status_code == 200
    history_page = history_response.get_data(as_text=True)
    assert "Personalized Only Digest" in history_page
    assert "Default Digest" in history_page
    assert "Personalized Variant Digest" not in history_page

    detail_response = client.get("/newsletters/2026-03-23")
    assert detail_response.status_code == 200
    detail_page = detail_response.get_data(as_text=True)
    assert "Personalized Only Digest" in detail_page
    assert "Personalized only body" in detail_page
