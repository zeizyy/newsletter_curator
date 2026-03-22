from __future__ import annotations

import importlib
import json

from curator.jobs import run_fetch_gmail_job, run_fetch_sources_job
from tests.fakes import (
    FakeArticleFetcher,
    FakeGmailService,
    FakeOpenAI,
    FakeSourceFetcher,
    make_gmail_message,
)
from tests.helpers import write_temp_config


def test_smoke_offline_pipeline(monkeypatch, repo_root, tmp_path):
    main = importlib.import_module("main")

    fixture_html = (repo_root / "tests" / "fixtures" / "newsletter_sample.html").read_text(
        encoding="utf-8"
    )
    service = FakeGmailService(
        messages=[
            make_gmail_message(
                message_id="msg-1",
                subject="Daily Macro Notes",
                from_header="Macro Letter <macro@example.com>",
                date_header="Sat, 21 Mar 2026 07:00:00 +0000",
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
                "date": "2026-03-21T06:00:00+00:00",
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
                "digest_recipients": ["integration@example.com"],
                "digest_subject": "Offline Smoke Digest",
            },
            "additional_sources": {"enabled": True},
            "limits": {
                "select_top_stories": 3,
                "final_top_stories": 3,
                "source_quotas": {"gmail": 2, "additional_source": 1},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    run_fetch_gmail_job(config, service, article_fetcher=article_fetcher)
    run_fetch_sources_job(config, source_fetcher=source_fetcher, article_fetcher=article_fetcher)

    sent_messages: list[dict] = []

    def fake_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        payload = {
            "to": to_address,
            "subject": subject,
            "body": body,
            "html_body": html_body or "",
        }
        sent_messages.append(payload)
        outbox_dir = tmp_path / "artifacts"
        outbox_dir.mkdir(exist_ok=True)
        artifact_path = outbox_dir / f"{len(sent_messages):02d}_{to_address.replace('@', '_')}.json"
        artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    monkeypatch.setattr(main, "OpenAI", lambda: fake_openai)
    monkeypatch.setattr(main, "send_email", fake_send_email)

    delivery_service = FakeGmailService(messages=[])
    main.run_job(config, delivery_service)

    artifact_path = tmp_path / "artifacts" / "01_integration_example.com.json"
    assert artifact_path.exists()
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["subject"] == "Offline Smoke Digest"
    assert "Rates reset changes software valuations" in payload["body"]
    assert "Read article" in payload["html_body"]
    assert source_fetcher.calls == 1
    assert len(article_fetcher.calls) == 3
    assert len(fake_openai.calls) == 0
