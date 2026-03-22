from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

from curator.jobs import get_repository_from_config, run_daily_orchestrator_job
from tests.fakes import FakeArticleFetcher, FakeGmailService, FakeSourceFetcher, make_gmail_message
from tests.helpers import write_temp_config


def test_daily_orchestrator_runs_fetch_and_delivery(monkeypatch, repo_root, tmp_path):
    main = importlib.import_module("main")
    now_utc = datetime.now(UTC)

    fixture_html = (repo_root / "tests" / "fixtures" / "newsletter_sample.html").read_text(
        encoding="utf-8"
    )
    service = FakeGmailService(
        messages=[
            make_gmail_message(
                message_id="msg-1",
                subject="Infra Letter",
                from_header="Infra Letter <infra@example.com>",
                date_header=format_datetime(now_utc - timedelta(hours=2)),
                html_body=fixture_html,
            )
        ]
    )
    source_fetcher = FakeSourceFetcher(
        [
            {
                "subject": "[markets] Rates reset",
                "from": "Macro Wire",
                "source_name": "Macro Wire",
                "source_type": "additional_source",
                "date": (now_utc - timedelta(hours=1)).isoformat(),
                "published_at": (now_utc - timedelta(hours=1)).isoformat(),
                "url": "https://example.com/markets/rates-reset",
                "anchor_text": "Rates reset changes software valuations",
                "context": "Repository context for rates reset.",
                "category": "Markets / stocks / macro / economy",
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
            "https://example.com/markets/rates-reset?utm=ignored": (
                "Unused duplicate path."
            ),
        }
    )

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "email": {
                "digest_recipients": ["pipeline@example.com"],
                "digest_subject": "Daily Orchestrator Digest",
            },
            "additional_sources": {"enabled": True, "hours": 24},
            "limits": {
                "select_top_stories": 2,
                "final_top_stories": 2,
                "source_quotas": {"gmail": 1, "additional_source": 1},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    config = main.load_config()
    repository = get_repository_from_config(config)

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

    result = run_daily_orchestrator_job(
        config,
        service,
        repository=repository,
        source_fetcher=source_fetcher,
        article_fetcher=article_fetcher,
        delivery_runner_fn=main.run_job,
    )

    assert result["status"] == "completed"
    assert result["stage_order"] == ["fetch_gmail", "fetch_sources", "deliver_digest"]
    assert result["completed_stages"] == ["fetch_gmail", "fetch_sources", "deliver_digest"]
    assert result["failed_stages"] == []
    assert result["stages"]["fetch_gmail"]["stories_seen"] > 0
    assert result["stages"]["fetch_sources"]["stories_seen"] == 1
    assert result["stages"]["deliver_digest"]["status"] == "completed"
    assert result["stages"]["deliver_digest"]["sent_recipients"] == 1
    assert source_fetcher.calls == 1
    assert len(sent_messages) == 1
    assert sent_messages[0]["subject"] == "Daily Orchestrator Digest"
    assert "Newsletter Digest" in sent_messages[0]["html_body"]
    assert "Read original" in sent_messages[0]["html_body"]
