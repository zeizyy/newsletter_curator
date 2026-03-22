from __future__ import annotations

import importlib
import re
from urllib.parse import urlparse

from curator.jobs import current_newsletter_date, get_repository_from_config
from tests.fakes import FakeGmailService, FakeOpenAI
from tests.helpers import create_completed_ingestion_run, write_temp_config


def test_newsletter_telemetry_tracking_endpoints(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "tracking": {"base_url": "http://curator.test"},
            "email": {
                "digest_recipients": ["tracking@example.com"],
                "digest_subject": "Tracked Digest",
            },
            "additional_sources": {"enabled": True, "hours": 48},
            "limits": {
                "select_top_stories": 2,
                "final_top_stories": 2,
                "source_quotas": {"gmail": 0, "additional_source": 2},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    repository.upsert_article_snapshot(
        repository.upsert_story(
            {
                "source_type": "additional_source",
                "source_name": "Macro Wire",
                "subject": "[markets] Rates reset",
                "url": "https://example.com/markets/rates-reset",
                "anchor_text": "Rates reset changes software valuations",
                "context": "Repository context for rates reset",
                "category": "Markets / stocks / macro / economy",
                "published_at": "2026-03-21T07:30:00+00:00",
                "summary": "Rates reset summary",
            },
            ingestion_run_id=ingestion_run_id,
        ),
        "Rates reset changes software valuations and reprices growth names.",
        summary_headline="Rates reset changes software valuations",
        summary_body="Key takeaways\n- Rates reset changes software valuations.\n\nWhy this matters to me\nThis matters for software multiples.",
        summary_model="gpt-5-mini",
        summarized_at="2026-03-21T08:00:00+00:00",
    )
    repository.upsert_article_snapshot(
        repository.upsert_story(
            {
                "source_type": "additional_source",
                "source_name": "AI Wire",
                "subject": "[ai] Open model pricing changed",
                "url": "https://example.com/ai/model-pricing",
                "anchor_text": "Open model pricing changed",
                "context": "Repository context for pricing",
                "category": "AI & ML industry developments",
                "published_at": "2026-03-21T06:00:00+00:00",
                "summary": "Pricing summary",
            },
            ingestion_run_id=ingestion_run_id,
        ),
        "Open model pricing changed and pushes buyers to recalculate inference budgets.",
        summary_headline="Open model pricing changed",
        summary_body="Key takeaways\n- Open model pricing changed.\n\nWhy this matters to me\nThis matters for inference budgets.",
        summary_model="gpt-5-mini",
        summarized_at="2026-03-21T08:05:00+00:00",
    )

    fake_openai = FakeOpenAI()
    sent_messages: list[dict] = []

    def fake_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        sent_messages.append(
            {
                "to": to_address,
                "subject": subject,
                "body": body,
                "html_body": html_body or "",
            }
        )

    monkeypatch.setattr(main, "OpenAI", lambda: fake_openai)
    monkeypatch.setattr(main, "send_email", fake_send_email)

    delivery_service = FakeGmailService(messages=[])
    result = main.run_job(config, delivery_service)
    stored_newsletter = repository.get_daily_newsletter(current_newsletter_date())

    assert result["status"] == "completed"
    assert stored_newsletter is not None
    assert len(sent_messages) == 1
    assert "/track/click/" not in stored_newsletter["html_body"]
    assert "/track/open/" not in stored_newsletter["html_body"]

    html_body = sent_messages[0]["html_body"]
    click_match = re.search(r'href="([^"]+/track/click/[^"]+)"', html_body)
    open_match = re.search(r'src="([^"]+/track/open/[^"]+\.gif)"', html_body)
    assert click_match is not None
    assert open_match is not None
    assert urlparse(click_match.group(1)).netloc == "curator.test"
    assert urlparse(open_match.group(1)).netloc == "curator.test"

    counts = repository.get_table_counts()
    assert counts["newsletter_telemetry"] == 1
    assert counts["tracked_links"] == 2
    assert counts["newsletter_open_events"] == 0
    assert counts["newsletter_click_events"] == 0

    client = admin_app.app.test_client()
    open_response = client.get(urlparse(open_match.group(1)).path, headers={"User-Agent": "PixelBot/1.0"})
    assert open_response.status_code == 200
    assert open_response.headers["Content-Type"] == "image/gif"

    click_response = client.get(
        urlparse(click_match.group(1)).path,
        headers={"User-Agent": "Browser/1.0"},
        follow_redirects=False,
    )
    assert click_response.status_code == 302
    assert click_response.headers["Location"] == "https://example.com/markets/rates-reset"

    counts = repository.get_table_counts()
    assert counts["newsletter_open_events"] == 1
    assert counts["newsletter_click_events"] == 1
