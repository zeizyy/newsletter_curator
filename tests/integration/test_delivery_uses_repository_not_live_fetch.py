from __future__ import annotations

import importlib
import json

from curator.jobs import get_repository_from_config
from tests.fakes import FakeGmailService, FakeOpenAI
from tests.helpers import create_completed_ingestion_run, write_temp_config


def test_delivery_uses_repository_not_live_fetch(monkeypatch, tmp_path):
    main = importlib.import_module("main")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["repository@example.com"],
                "digest_subject": "Repository Delivery Digest",
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
        "Rates reset changes software valuations and reprices growth.",
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
    )

    service = FakeGmailService(messages=[])
    fake_openai = FakeOpenAI()
    sent_messages: list[dict] = []

    def fail_live_article_fetch(*args, **kwargs):
        raise AssertionError("Delivery should not fetch article text live for repository stories.")

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
    monkeypatch.setattr(main, "fetch_article_text", fail_live_article_fetch)
    monkeypatch.setattr(main, "send_email", fake_send_email)

    main.run_job(config, service)

    assert len(sent_messages) == 1
    payload = sent_messages[0]
    assert payload["subject"] == "Repository Delivery Digest"
    assert payload["to"] == "repository@example.com"
    assert "Rates reset changes software valuations" in payload["body"]
    assert "Open model pricing changed and" in payload["body"]
    assert "Read signal" in payload["html_body"]
    assert "Mar 21, 7:30 AM UTC" in payload["html_body"]
    assert "Market Tape" in payload["html_body"]
    assert len(fake_openai.calls) == 3
