from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
import re

from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run, write_temp_config


def test_subscriber_onboarding_rates_recent_stories(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    now_utc = datetime.now(UTC)
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "AI Wire",
            "subject": "Open model pricing changed",
            "url": "https://example.com/ai/model-pricing",
            "anchor_text": "Open model pricing changed",
            "context": "Inference pricing shifts buyer budgets.",
            "category": "AI & ML industry developments",
            "published_at": (now_utc - timedelta(days=1)).isoformat(),
            "summary": "Pricing summary",
        },
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        "Open model pricing changed and pushes buyers to recalculate inference budgets.",
        summary_headline="Open model pricing changed",
        summary_body="New inference pricing is forcing buyers to recalculate budgets.",
        summary_model="gpt-5-mini",
        summarized_at=now_utc.isoformat(),
    )
    week_old_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "AI Wire",
            "subject": "Six day old story",
            "url": "https://example.com/ai/six-day-story",
            "anchor_text": "Six day old story",
            "context": "A story still inside the one-week tuning window.",
            "category": "AI & ML industry developments",
            "published_at": (now_utc - timedelta(days=6)).isoformat(),
            "summary": "Six day summary",
        },
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_article_snapshot(
        week_old_story_id,
        "A six day old story should still be available for preference tuning.",
        summary_headline="Six day old story",
        summary_body="This story is still inside the last week's news window.",
        summary_model="gpt-5-mini",
        summarized_at=now_utc.isoformat(),
    )
    stale_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Old Wire",
            "subject": "Old story",
            "url": "https://example.com/old",
            "anchor_text": "Old story",
            "context": "Old context",
            "category": "Tech company news & strategy",
            "published_at": (now_utc - timedelta(days=8)).isoformat(),
            "summary": "Old summary",
        },
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_article_snapshot(
        stale_story_id,
        "Old article text.",
        summary_headline="Old story",
        summary_body="Old summary body.",
        summary_model="gpt-5-mini",
        summarized_at=now_utc.isoformat(),
    )
    subscriber = repository.upsert_subscriber("reader@example.com")
    repository.upsert_subscriber_story_preference_memory(
        int(subscriber["id"]),
        memory_text="Prefers practical AI pricing and buyer adoption signals.",
        clicked_story_count=4,
    )
    session = repository.create_subscriber_session(int(subscriber["id"]))

    client = admin_app.app.test_client()
    client.set_cookie(admin_app.SUBSCRIBER_SESSION_COOKIE, session["token"])
    response = client.get("/onboarding")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Tune your digest" in page
    assert "Open model pricing changed" in page
    assert "Six day old story" in page
    assert "Old story" not in page
    assert "Recent news" not in page
    assert "Swipe through" not in page
    assert "left arrow" not in page
    assert "right arrow" not in page
    assert "Your thumbs" in page
    assert "No explicit thumbs have been logged yet." in page
    assert "Your learned signal" in page
    assert "Prefers practical AI pricing and buyer adoption signals." in page
    assert "Less like this" in page
    assert "More like this" in page
    assert "You're all tuned up" in page

    token_match = re.search(r'data-click-token="([^"]+)"', page)
    assert token_match is not None
    feedback_response = client.post(
        "/onboarding/feedback",
        json={"click_token": token_match.group(1), "sentiment": "down"},
    )

    assert feedback_response.status_code == 200
    assert feedback_response.get_json()["status"] == "recorded"
    interactions = repository.list_clicked_stories_for_subscriber(int(subscriber["id"]))
    assert interactions[0]["signal"] == "feedback"
    assert interactions[0]["sentiment"] == "down"
    assert interactions[0]["title"] == "Open model pricing changed"

    next_response = client.get("/onboarding")
    next_page = next_response.get_data(as_text=True)
    assert "Open model pricing changed" in next_page
    assert "data-feedback-empty hidden" in next_page
    assert "Your thumbs" in next_page
    assert "Less like this" in next_page
    assert '<span class="rating-title">Open model pricing changed</span>' in next_page
    assert "<strong data-less-count>1</strong>" in next_page
    assert "Six day old story" in next_page
