from __future__ import annotations

import datetime as dt
import importlib
from types import SimpleNamespace

from curator.jobs import get_repository_from_config
from tests.helpers import write_temp_config


def test_admin_newsletter_analytics_page(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "tracking": {"base_url": "http://curator.test"},
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    config = main.load_config()
    repository = get_repository_from_config(config)

    today = dt.datetime.now(dt.UTC).date()
    newsletter_a_date = today.isoformat()
    newsletter_b_date = (today - dt.timedelta(days=1)).isoformat()
    delivery_run_a_id = repository.create_delivery_run(metadata={"test": True})
    repository.complete_delivery_run(
        delivery_run_a_id,
        status="completed",
        metadata={"pipeline_result": {"sent_recipients": 2}},
    )
    delivery_run_a_personalized_id = repository.create_delivery_run(metadata={"test": True})
    repository.complete_delivery_run(
        delivery_run_a_personalized_id,
        status="completed",
        metadata={"pipeline_result": {"sent_recipients": 3}},
    )
    delivery_run_b_id = repository.create_delivery_run(metadata={"test": True})
    repository.complete_delivery_run(
        delivery_run_b_id,
        status="completed",
        metadata={"pipeline_result": {"sent_recipients": 4}},
    )

    newsletter_a_id = repository.upsert_daily_newsletter(
        newsletter_date=newsletter_a_date,
        delivery_run_id=delivery_run_a_id,
        subject="Digest A",
        body="Digest A body",
        html_body="<html><body>Digest A</body></html>",
        selected_items=[
            {"title": "AI infra economics", "url": "https://example.com/ai-infra"},
            {"title": "Search interface reset", "url": "https://example.com/search-reset"},
        ],
        metadata={"test": True},
    )
    newsletter_a_personalized_id = repository.upsert_daily_newsletter(
        newsletter_date=newsletter_a_date,
        audience_key="df18eaca02a227a7",
        delivery_run_id=delivery_run_a_personalized_id,
        subject="Digest A Personalized",
        body="Digest A personalized body",
        html_body="<html><body>Digest A Personalized</body></html>",
        selected_items=[
            {"title": "AI infra economics", "url": "https://example.com/ai-infra"},
            {"title": "GPU capex revival", "url": "https://example.com/gpu-capex"},
        ],
        metadata={"test": True, "personalized": True},
    )
    newsletter_b_id = repository.upsert_daily_newsletter(
        newsletter_date=newsletter_b_date,
        delivery_run_id=delivery_run_b_id,
        subject="Digest B",
        body="Digest B body",
        html_body="<html><body>Digest B</body></html>",
        selected_items=[
            {"title": "Model margin compression", "url": "https://example.com/model-margins"},
        ],
        metadata={"test": True},
    )

    open_token_a = repository.ensure_newsletter_open_token(newsletter_a_id)
    open_token_b = repository.ensure_newsletter_open_token(newsletter_b_id)
    tracked_links_a = repository.ensure_tracked_links(
        newsletter_a_id,
        [
            {"title": "AI infra economics", "url": "https://example.com/ai-infra"},
            {"title": "Search interface reset", "url": "https://example.com/search-reset"},
        ],
    )
    tracked_links_a_personalized = repository.ensure_tracked_links(
        newsletter_a_personalized_id,
        [
            {"title": "AI infra economics", "url": "https://example.com/ai-infra"},
            {"title": "GPU capex revival", "url": "https://example.com/gpu-capex"},
        ],
    )
    tracked_links_b = repository.ensure_tracked_links(
        newsletter_b_id,
        [
            {"title": "Model margin compression", "url": "https://example.com/model-margins"},
        ],
    )

    ai_infra_click = next(
        link["click_token"] for link in tracked_links_a if link["story_title"] == "AI infra economics"
    )
    search_reset_click = next(
        link["click_token"]
        for link in tracked_links_a
        if link["story_title"] == "Search interface reset"
    )
    gpu_capex_click = next(
        link["click_token"]
        for link in tracked_links_a_personalized
        if link["story_title"] == "GPU capex revival"
    )
    model_margin_click = tracked_links_b[0]["click_token"]

    repository.record_newsletter_open(open_token_a, user_agent="Mail/1.0", ip_address="1.1.1.1")
    repository.record_newsletter_open(open_token_a, user_agent="Mail/1.0", ip_address="1.1.1.1")
    repository.record_newsletter_open(open_token_a, user_agent="Mail/2.0", ip_address="2.2.2.2")
    open_token_a_personalized = repository.ensure_newsletter_open_token(newsletter_a_personalized_id)
    repository.record_newsletter_open(
        open_token_a_personalized,
        user_agent="Mail/2.0",
        ip_address="2.2.2.2",
    )
    repository.record_newsletter_open(
        open_token_a_personalized,
        user_agent="Mail/4.0",
        ip_address="4.4.4.4",
    )
    repository.record_newsletter_open(open_token_b, user_agent="Mail/3.0", ip_address="3.3.3.3")

    repository.record_newsletter_click(ai_infra_click, user_agent="Mail/1.0", ip_address="1.1.1.1")
    repository.record_newsletter_click(ai_infra_click, user_agent="Mail/1.0", ip_address="1.1.1.1")
    repository.record_newsletter_click(search_reset_click, user_agent="Mail/2.0", ip_address="2.2.2.2")
    repository.record_newsletter_click(gpu_capex_click, user_agent="Mail/2.0", ip_address="2.2.2.2")
    repository.record_newsletter_click(gpu_capex_click, user_agent="Mail/4.0", ip_address="4.4.4.4")
    repository.record_newsletter_click(model_margin_click, user_agent="Mail/3.0", ip_address="3.3.3.3")

    client = admin_app.app.test_client()
    response = client.get("/analytics")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Insight Ledger" in html
    assert "Telemetry Review" in html
    assert "Command Rail" in html
    assert "Tracked opens are approximate" in html
    assert "Digest A" in html
    assert "Digest A Personalized" not in html
    assert "Digest B" in html
    assert "5 opens" in html
    assert "3 unique" in html
    assert "AI infra economics" in html
    assert "5 clicks" in html
    assert "6 clicks" in html
    assert "5 unique clicks" in html
    assert "14 story deliveries" in html
    assert "10 story deliveries" in html
    assert "4 story deliveries" in html
    assert "35.7%" in html
    assert "30.0%" in html
    assert "25.0%" in html
    assert "100.0%" not in html


def test_admin_newsletter_analytics_page_caps_recent_newsletters_and_top_clicked(monkeypatch):
    admin_app = importlib.import_module("admin_app")
    monkeypatch.setenv("CURATOR_ADMIN_TOKEN", "ops-secret")

    captured: dict[str, tuple[int, bool] | None] = {
        "recent_newsletters": None,
        "top_clicked_stories": None,
    }

    def list_newsletter_analytics(*, limit: int, include_all_audiences: bool):
        captured["recent_newsletters"] = (limit, include_all_audiences)
        return []

    def list_top_clicked_stories(*, trailing_days: int, limit: int, include_all_audiences: bool):
        assert trailing_days == 30
        captured["top_clicked_stories"] = (limit, include_all_audiences)
        return []

    fake_repository = SimpleNamespace(
        list_newsletter_analytics=list_newsletter_analytics,
        get_newsletter_aggregate_stats=lambda **_: [],
        list_top_clicked_stories=list_top_clicked_stories,
    )

    monkeypatch.setattr(admin_app, "load_merged_config", lambda: {})
    monkeypatch.setattr(admin_app, "load_repository", lambda _merged: fake_repository)

    client = admin_app.app.test_client()
    response = client.get("/analytics", headers={"X-Admin-Token": "ops-secret"})

    assert response.status_code == 200
    assert captured["recent_newsletters"] == (7, True)
    assert captured["top_clicked_stories"] == (10, True)
