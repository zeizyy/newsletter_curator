from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

from curator.jobs import get_repository_from_config, run_fetch_gmail_job
from tests.fakes import FakeArticleFetcher, FakeGmailService, FakeOpenAI, make_gmail_message
from tests.helpers import write_temp_config


def test_gmail_ingest_then_delivery_from_db(monkeypatch, repo_root, tmp_path):
    main = importlib.import_module("main")
    now_utc = datetime.now(UTC)
    gmail_timestamp = now_utc - timedelta(hours=2)

    fixture_html = (repo_root / "tests" / "fixtures" / "newsletter_sample.html").read_text(
        encoding="utf-8"
    )
    ingest_service = FakeGmailService(
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
    article_fetcher = FakeArticleFetcher(
        {
            "https://example.com/markets/rates-reset": (
                "Rates reset changes software valuations and reprices growth expectations."
            ),
            "https://example.com/ai/chips": (
                "Chip supply is tightening across cloud vendors and shifting deployment timelines."
            ),
        }
    )

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "additional_sources": {"enabled": False},
            "development": {"fake_inference": True},
            "email": {
                "digest_recipients": ["gmail-db@example.com"],
                "digest_subject": "Gmail DB Digest",
            },
            "limits": {
                "select_top_stories": 1,
                "final_top_stories": 1,
                "source_quotas": {"gmail": 1, "additional_source": 0},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    fetch_result = run_fetch_gmail_job(config, ingest_service, article_fetcher=article_fetcher)
    repository = get_repository_from_config(config)
    counts = repository.get_table_counts()

    fake_openai = FakeOpenAI()
    sent_messages: list[dict] = []

    def fail_live_gmail_reads(*args, **kwargs):
        raise AssertionError("Delivery should use repository-stored Gmail stories, not live Gmail reads.")

    def fail_live_article_fetch(*args, **kwargs):
        raise AssertionError("Delivery should use repository-stored Gmail article snapshots.")

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
    monkeypatch.setattr(main, "list_message_ids_for_label", fail_live_gmail_reads)
    monkeypatch.setattr(main, "get_message", fail_live_gmail_reads)
    monkeypatch.setattr(main, "fetch_article_text", fail_live_article_fetch)
    monkeypatch.setattr(main, "send_email", fake_send_email)

    delivery_service = FakeGmailService(messages=[])
    main.run_job(config, delivery_service)

    assert fetch_result["status"] == "completed"
    assert counts["fetched_stories"] == 2
    assert counts["article_snapshots"] == 2
    assert len(sent_messages) == 1
    payload = sent_messages[0]
    assert payload["subject"] == "Gmail DB Digest"
    assert payload["to"] == "gmail-db@example.com"
    assert (
        "Chip supply is tightening across cloud" in payload["body"]
        or "Rates reset changes software valuations" in payload["body"]
    )


def test_gmail_ingest_prefers_article_timestamp_over_email_timestamp(monkeypatch, repo_root, tmp_path):
    now_utc = datetime.now(UTC)
    email_timestamp = now_utc - timedelta(hours=2)
    article_timestamp = "2026-03-21T12:15:00+00:00"

    fixture_html = (repo_root / "tests" / "fixtures" / "newsletter_sample.html").read_text(
        encoding="utf-8"
    )
    ingest_service = FakeGmailService(
        messages=[
            make_gmail_message(
                message_id="msg-1",
                subject="Daily Macro Notes",
                from_header="Macro Letter <macro@example.com>",
                date_header=format_datetime(email_timestamp),
                html_body=fixture_html,
            )
        ]
    )

    def fake_article_fetcher(url: str, max_article_chars: int, timeout: int = 25, retries: int = 3):
        return {
            "article_text": "Rates reset changes software valuations and reprices growth expectations.",
            "document_title": "Rates reset",
            "document_excerpt": "Macro reset article excerpt.",
            "published_at": article_timestamp,
            "access_blocked": False,
            "access_reason": "",
            "access_signals": {},
        }

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "additional_sources": {"enabled": False},
            "development": {"fake_inference": True},
            "limits": {
                "select_top_stories": 1,
                "final_top_stories": 1,
                "source_quotas": {"gmail": 1, "additional_source": 0},
            },
        },
    )

    main = importlib.import_module("main")
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    result = run_fetch_gmail_job(config, ingest_service, article_fetcher=fake_article_fetcher)
    repository = get_repository_from_config(config)
    stories = repository.list_stories(source_type="gmail")

    assert result["status"] == "completed"
    assert len(stories) == 2
    assert {story["published_at"] for story in stories} == {article_timestamp}
