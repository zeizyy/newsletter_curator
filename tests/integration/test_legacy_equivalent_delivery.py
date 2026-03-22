from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

from curator.jobs import run_fetch_gmail_job, run_fetch_sources_job
from tests.fakes import (
    FakeArticleFetcher,
    FakeGmailService,
    FakeOpenAI,
    FakeSourceFetcher,
    make_gmail_message,
)
from tests.helpers import write_temp_config


def test_legacy_equivalent_delivery(monkeypatch, repo_root, tmp_path):
    main = importlib.import_module("main")
    now_utc = datetime.now(UTC)
    gmail_timestamp = now_utc - timedelta(hours=2)
    source_timestamp = now_utc - timedelta(hours=1)

    fixture_html = (repo_root / "tests" / "fixtures" / "newsletter_sample.html").read_text(
        encoding="utf-8"
    )
    service = FakeGmailService(
        messages=[
            make_gmail_message(
                message_id="msg-1",
                subject="Daily Macro Notes",
                from_header="Macro Letter <macro@example.com>",
                date_header=format_datetime(gmail_timestamp),
                html_body=fixture_html,
            )
        ]
    )
    source_fetcher = FakeSourceFetcher(
        [
            {
                "subject": "[ai] Open model pricing changed",
                "from": "AI Wire",
                "source_name": "AI Wire",
                "source_type": "additional_source",
                "date": source_timestamp.isoformat(),
                "published_at": source_timestamp.isoformat(),
                "url": "https://example.com/ai/model-pricing",
                "anchor_text": "Open model pricing changed",
                "context": "Model pricing moved again across the stack.",
            }
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            "https://example.com/markets/rates-reset": (
                "Rates reset changes software valuations and reprices future growth expectations."
            ),
            "https://example.com/ai/chips": (
                "Chip supply is tightening across cloud vendors and shifting deployment timelines."
            ),
            "https://example.com/ai/model-pricing": (
                "Open model pricing changed again and forces buyers to reconsider inference budgets."
            ),
        }
    )
    fake_openai = FakeOpenAI()

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "email": {
                "digest_recipients": ["entrypoint@example.com"],
                "digest_subject": "Legacy Equivalent Digest",
            },
            "additional_sources": {"enabled": True},
            "limits": {
                "select_top_stories": 3,
                "final_top_stories": 3,
                "source_quotas": {"gmail": 2, "additional_source": 1},
            },
        },
    )

    sent_messages: list[dict] = []

    def fake_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        payload = {
            "to": to_address,
            "subject": subject,
            "body": body,
            "html_body": html_body or "",
        }
        sent_messages.append(payload)
        artifact_path = tmp_path / "legacy_equivalent_digest.json"
        artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    run_fetch_gmail_job(main.load_config(), service, article_fetcher=article_fetcher)
    run_fetch_sources_job(
        main.load_config(),
        source_fetcher=source_fetcher,
        article_fetcher=article_fetcher,
    )

    delivery_service = FakeGmailService(messages=[])
    monkeypatch.setattr(main, "get_gmail_service", lambda paths: delivery_service)
    monkeypatch.setattr(main, "OpenAI", lambda: fake_openai)
    monkeypatch.setattr(main, "send_email", fake_send_email)

    main.main()

    artifact_path = tmp_path / "legacy_equivalent_digest.json"
    assert artifact_path.exists()
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["subject"] == "Legacy Equivalent Digest"
    assert "Rates reset changes software valuations" in payload["body"]
    assert "Open model pricing changed again" in payload["body"]
    assert payload["to"] == "entrypoint@example.com"
    assert len(sent_messages) == 1
    assert source_fetcher.calls == 1
    assert len(article_fetcher.calls) == 3
    assert len(fake_openai.calls) == 0
