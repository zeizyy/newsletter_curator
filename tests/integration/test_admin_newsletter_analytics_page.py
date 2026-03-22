from __future__ import annotations

import datetime as dt
import importlib

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

    newsletter_a_id = repository.upsert_daily_newsletter(
        newsletter_date=newsletter_a_date,
        subject="Digest A",
        body="Digest A body",
        html_body="<html><body>Digest A</body></html>",
        selected_items=[
            {"title": "AI infra economics", "url": "https://example.com/ai-infra"},
            {"title": "Search interface reset", "url": "https://example.com/search-reset"},
        ],
        metadata={"test": True},
    )
    newsletter_b_id = repository.upsert_daily_newsletter(
        newsletter_date=newsletter_b_date,
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
    model_margin_click = tracked_links_b[0]["click_token"]

    repository.record_newsletter_open(open_token_a, user_agent="Mail/1.0", ip_address="1.1.1.1")
    repository.record_newsletter_open(open_token_a, user_agent="Mail/1.0", ip_address="1.1.1.1")
    repository.record_newsletter_open(open_token_a, user_agent="Mail/2.0", ip_address="2.2.2.2")
    repository.record_newsletter_open(open_token_b, user_agent="Mail/3.0", ip_address="3.3.3.3")

    repository.record_newsletter_click(ai_infra_click, user_agent="Mail/1.0", ip_address="1.1.1.1")
    repository.record_newsletter_click(ai_infra_click, user_agent="Mail/1.0", ip_address="1.1.1.1")
    repository.record_newsletter_click(search_reset_click, user_agent="Mail/2.0", ip_address="2.2.2.2")
    repository.record_newsletter_click(model_margin_click, user_agent="Mail/3.0", ip_address="3.3.3.3")

    client = admin_app.app.test_client()
    response = client.get("/analytics")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Newsletter Analytics" in html
    assert "Tracked opens are approximate" in html
    assert "Digest A" in html
    assert "Digest B" in html
    assert "3 opens" in html
    assert "2 unique" in html
    assert "AI infra economics" in html
    assert "2 clicks" in html
    assert "4 clicks" in html
    assert "3 unique clicks" in html
    assert "100.0%" in html
