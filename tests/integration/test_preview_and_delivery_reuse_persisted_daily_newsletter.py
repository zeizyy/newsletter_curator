from __future__ import annotations

import importlib

from curator.jobs import current_newsletter_date, get_repository_from_config
from tests.fakes import FakeGmailService, FakeOpenAI
from tests.helpers import create_completed_ingestion_run, write_temp_config


class FailIfCalledOpenAI:
    def __init__(self):
        raise AssertionError("Cached daily newsletter should prevent new OpenAI calls.")


def test_preview_and_delivery_reuse_persisted_daily_newsletter(monkeypatch, tmp_path):
    main = importlib.import_module("main")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["cached@example.com"],
                "digest_subject": "Cached Daily Digest",
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
    monkeypatch.setattr(main, "OpenAI", lambda: fake_openai)

    first_preview = main.preview_job(config)
    stored_newsletter = repository.get_daily_newsletter(current_newsletter_date())

    assert first_preview["status"] == "completed"
    assert first_preview["cached_newsletter"] is False
    assert first_preview["preview"] is not None
    assert len(fake_openai.calls) == 1
    assert stored_newsletter is not None
    assert stored_newsletter["subject"] == "Cached Daily Digest"
    assert "Rates reset changes software valuations" in stored_newsletter["body"]
    assert len(stored_newsletter["selected_items"]) == 2

    monkeypatch.setattr(main, "OpenAI", FailIfCalledOpenAI)
    second_preview = main.preview_job(config)

    assert second_preview["status"] == "completed"
    assert second_preview["cached_newsletter"] is True
    assert second_preview["preview"] is not None
    assert second_preview["preview"]["body"] == stored_newsletter["body"]
    assert second_preview["preview"]["html_body"] == stored_newsletter["html_body"]

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

    monkeypatch.setattr(main, "send_email", fake_send_email)
    delivery_service = FakeGmailService(messages=[])
    delivery_result = main.run_job(config, delivery_service)

    assert delivery_result["status"] == "completed"
    assert delivery_result["cached_newsletter"] is True
    assert len(sent_messages) == 1
    assert sent_messages[0]["subject"] == "Cached Daily Digest"
    assert sent_messages[0]["body"] == stored_newsletter["body"]
    assert sent_messages[0]["html_body"] == stored_newsletter["html_body"]
