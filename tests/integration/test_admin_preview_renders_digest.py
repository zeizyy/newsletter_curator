from __future__ import annotations

import importlib

from curator.jobs import get_repository_from_config
from tests.fakes import FakeOpenAI
from tests.helpers import create_completed_ingestion_run, write_temp_config


def test_admin_preview_renders_digest(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")
    jobs = importlib.import_module("curator.jobs")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["preview@example.com"],
                "digest_subject": "Preview Digest",
            },
            "tracking": {"base_url": "https://curator.example.com"},
            "additional_sources": {"enabled": True, "hours": 100000},
            "limits": {
                "select_top_stories": 2,
                "final_top_stories": 2,
                "source_quotas": {"gmail": 0, "additional_source": 2},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "current_newsletter_date", lambda: "2026-03-24")
    monkeypatch.setattr(jobs, "current_newsletter_date", lambda: "2026-03-24")
    monkeypatch.setenv("CURATOR_ADMIN_ENABLE_PREVIEW", "1")
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
                    "published_at": "2026-03-24T07:30:00+00:00",
                "summary": "Rates reset summary",
            },
            ingestion_run_id=ingestion_run_id,
        ),
        "Rates reset changes software valuations and reprices growth names.",
        summary_headline="Rates reset changes software valuations",
        summary_body="Rates reset changes software valuations and reprices growth names.",
        summary_model="gpt-5-mini",
            summarized_at="2026-03-24T07:35:00+00:00",
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
                    "published_at": "2026-03-24T06:00:00+00:00",
                "summary": "Pricing summary",
            },
            ingestion_run_id=ingestion_run_id,
        ),
        "Open model pricing changed and pushes buyers to recalculate inference budgets.",
        summary_headline="Open model pricing changed",
        summary_body="Open model pricing changed and pushes buyers to recalculate inference budgets.",
        summary_model="gpt-5-mini",
            summarized_at="2026-03-24T06:05:00+00:00",
    )

    def fail_live_email_send(*args, **kwargs):
        raise AssertionError("Preview should not send actual email.")

    monkeypatch.setattr(main, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(main, "send_email", fail_live_email_send)

    client = admin_app.app.test_client()
    response = client.get("/preview")
    assert response.status_code in {200, 202}
    if response.status_code == 202:
        assert "generation has started" in response.get_data(as_text=True).lower()
        for _ in range(20):
            response = client.get("/preview")
            if response.status_code == 200:
                break

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Briefing Desk" in page
    assert "Command Rail" in page
    assert "Preview Digest" in page
    assert "Market Tape Preview" in page
    assert "Rates reset changes software valuations" in page
    assert "Open model pricing changed" in page
    assert "Read original" in page
    assert 'target="_blank"' in page
    assert "Mar 24, 12:30 AM PT" in page
    assert 'font-family:Georgia' in page
    assert 'role="presentation"' not in page
    assert "data-story-timestamp" in page
    assert "Intl.DateTimeFormat" in page
    assert "Email-Safe Template" in page

    email_safe_response = client.get("/preview?template=email_safe")
    assert email_safe_response.status_code in {200, 202}
    if email_safe_response.status_code == 202:
        assert "generation has started" in email_safe_response.get_data(as_text=True).lower()
        for _ in range(20):
            email_safe_response = client.get("/preview?template=email_safe")
            if email_safe_response.status_code == 200:
                break
    assert email_safe_response.status_code == 200
    email_safe_page = email_safe_response.get_data(as_text=True)
    assert "Email-Safe Preview" in email_safe_page
    assert "Briefing Desk" in email_safe_page
    assert "Preview Digest" in email_safe_page
    assert "Rates reset changes software valuations" in email_safe_page
    assert 'role="presentation"' in email_safe_page
    assert "AI Signal Daily" in email_safe_page
    assert "Subscriber settings" in email_safe_page
    assert "https://curator.example.com/settings" in email_safe_page
    assert "max-width:640px" in email_safe_page
    assert "border-collapse:collapse" in email_safe_page
    assert 'font-family:Georgia' in email_safe_page

    gmail_lab_response = client.get("/preview?template=gmail_lab")
    assert gmail_lab_response.status_code in {200, 202}
    if gmail_lab_response.status_code == 202:
        assert "generation has started" in gmail_lab_response.get_data(as_text=True).lower()
        for _ in range(20):
            gmail_lab_response = client.get("/preview?template=gmail_lab")
            if gmail_lab_response.status_code == 200:
                break
    assert gmail_lab_response.status_code == 200
    gmail_lab_page = gmail_lab_response.get_data(as_text=True)
    assert "Gmail App Lab" in gmail_lab_page
    assert "Briefing Desk" in gmail_lab_page
    assert "This is a local Gmail-focused approximation" in gmail_lab_page
    assert "Browser Review Template" in gmail_lab_page
    assert "Email-Safe Delivery Template" in gmail_lab_page
    assert 'title="Browser review template"' in gmail_lab_page
    assert 'title="Email-safe template"' in gmail_lab_page
    assert "srcdoc=" in gmail_lab_page
