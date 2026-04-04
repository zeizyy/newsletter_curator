from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from curator.jobs import get_repository_from_config
from tests.fakes import FakeGmailService
from tests.helpers import create_completed_ingestion_run
from tests.helpers import write_temp_config


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 24, 18, 0, 0, tzinfo=tz or UTC)


def _seed_cached_newsletter(repository, newsletter_date: str) -> None:
    repository.upsert_daily_newsletter(
        newsletter_date=newsletter_date,
        subject="Cached Daily Digest",
        body="Top story body",
        html_body=(
            '<html><body><a href="https://example.com/markets/rates-reset">'
            "Read original</a></body></html>"
        ),
        content={"render_groups": {}},
        selected_items=[
            {
                "url": "https://example.com/markets/rates-reset",
                "anchor_text": "Rates reset changes software valuations",
                "source_name": "Macro Wire",
                "source_type": "additional_source",
                "category": "Markets / stocks / macro / economy",
            }
        ],
        metadata={},
        delivery_run_id=None,
    )


def _seed_story(
    repository,
    *,
    ingestion_run_id: int,
    source_name: str,
    subject: str,
    url: str,
    anchor_text: str,
    context: str,
    category: str,
    article_text: str,
    summary_body: str,
    published_at: str,
    summarized_at: str,
) -> None:
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": source_name,
            "subject": subject,
            "url": url,
            "anchor_text": anchor_text,
            "context": context,
            "category": category,
            "published_at": published_at,
            "summary": summary_body,
        },
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        article_text,
        summary_headline=anchor_text,
        summary_body=summary_body,
        summary_model="gpt-5-mini",
        summarized_at=summarized_at,
    )


def test_deliver_digest_dry_run_recipient_override(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")
    deliver_digest = importlib.import_module("deliver_digest")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["fallback-a@example.com", "fallback-b@example.com"],
                "digest_subject": "Cached Daily Digest",
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_cached_newsletter(repository, "2026-03-24")
    monkeypatch.setattr(
        deliver_digest,
        "parse_args",
        lambda: SimpleNamespace(dry_run_recipient="dry-run@example.com"),
    )
    rendered_output: list[str] = []
    monkeypatch.setattr(
        deliver_digest,
        "print",
        lambda text: rendered_output.append(text),
        raising=False,
    )
    monkeypatch.setattr(main, "get_gmail_service", lambda paths: FakeGmailService(messages=[]))

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

    deliver_digest.main()
    result = json.loads(rendered_output[-1])

    assert result["status"] == "completed"
    assert result["cached_newsletter"] is True
    assert result["recipient_source"] == "dry_run_override"
    assert result["sent_recipients"] == 1
    assert result["delivery_subscribers"] == [
        {
            "email": "dry-run@example.com",
            "persona_text": "",
            "preferred_sources": [],
            "profile_key": result["delivery_subscribers"][0]["profile_key"],
        }
    ]
    assert [message["to"] for message in sent_messages] == ["dry-run@example.com"]


def test_cached_delivery_emits_structured_journey_events(monkeypatch, tmp_path, capsys):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["cached@example.com"],
                "digest_subject": "Cached Daily Digest",
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_cached_newsletter(repository, "2026-03-24")

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

    result = main.run_job(config, FakeGmailService(messages=[]))
    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines() if line.strip()]

    assert result["status"] == "completed"
    assert result["cached_newsletter"] is True
    assert [message["to"] for message in sent_messages] == ["cached@example.com"]
    assert any(entry["event"] == "delivery_started" for entry in events)
    assert any(entry["event"] == "delivery_cached_newsletter_used" for entry in events)
    assert any(entry["event"] == "delivery_send_started" for entry in events)
    assert any(entry["event"] == "delivery_send_completed" for entry in events)
    assert any(
        entry["event"] == "delivery_completed" and entry["cached_newsletter"] is True
        for entry in events
    )


def test_cached_delivery_retries_transient_send_failure(monkeypatch, tmp_path, capsys):
    main = importlib.import_module("main")
    gmail = importlib.import_module("curator.gmail")
    jobs = importlib.import_module("curator.jobs")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["cached@example.com"],
                "digest_subject": "Cached Daily Digest",
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)
    monkeypatch.setattr(gmail.time, "sleep", lambda _seconds: None)

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_cached_newsletter(repository, "2026-03-24")

    attempts: list[str] = []

    def flaky_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        attempts.append(to_address)
        if len(attempts) == 1:
            raise BrokenPipeError("broken pipe")

    monkeypatch.setattr(main, "send_email", flaky_send_email)

    result = main.run_job(config, FakeGmailService(messages=[]))
    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines() if line.strip()]

    assert result["status"] == "completed"
    assert result["sent_recipients"] == 1
    assert result["failed_recipient_count"] == 0
    assert attempts == ["cached@example.com", "cached@example.com"]
    retry_events = [entry for entry in events if entry["event"] == "delivery_recipient_send_retry"]
    assert len(retry_events) == 1
    assert retry_events[0]["recipient"] == "cached@example.com"
    assert any(entry["event"] == "delivery_recipient_send_completed" for entry in events)


def test_cached_delivery_reports_partial_failure_and_continues(monkeypatch, tmp_path, capsys):
    main = importlib.import_module("main")
    gmail = importlib.import_module("curator.gmail")
    jobs = importlib.import_module("curator.jobs")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["fail@example.com", "ok@example.com"],
                "digest_subject": "Cached Daily Digest",
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)
    monkeypatch.setattr(gmail.time, "sleep", lambda _seconds: None)

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_cached_newsletter(repository, "2026-03-24")

    sent_messages: list[str] = []

    def selective_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        if to_address == "fail@example.com":
            raise BrokenPipeError("broken pipe")
        sent_messages.append(to_address)

    monkeypatch.setattr(main, "send_email", selective_send_email)

    result = main.run_job(config, FakeGmailService(messages=[]))
    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines() if line.strip()]

    assert result["status"] == "partial_failure"
    assert result["sent_recipients"] == 1
    assert result["failed_recipient_count"] == 1
    assert result["failed_recipients"] == [
        {
            "recipient": "fail@example.com",
            "attempts": 3,
            "error": "broken pipe",
            "retryable": True,
        }
    ]
    assert sent_messages == ["ok@example.com"]
    completion_event = next(entry for entry in events if entry["event"] == "delivery_send_completed")
    assert completion_event["status"] == "partial_failure"
    assert completion_event["failed_recipients"] == 1
    assert any(
        entry["event"] == "delivery_recipient_send_failed" and entry["recipient"] == "fail@example.com"
        for entry in events
    )


def test_cached_delivery_verifies_sent_message_before_retrying_ambiguous_failure(monkeypatch, tmp_path, capsys):
    main = importlib.import_module("main")
    gmail = importlib.import_module("curator.gmail")
    jobs = importlib.import_module("curator.jobs")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["cached@example.com"],
                "digest_subject": "Cached Daily Digest",
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)
    monkeypatch.setattr(gmail.time, "sleep", lambda _seconds: None)

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_cached_newsletter(repository, "2026-03-24")
    service = FakeGmailService(messages=[])

    original_send_email = gmail.send_email
    attempts: list[str] = []

    def send_then_break(
        service,
        to_address: str,
        subject: str,
        body: str,
        html_body: str | None = None,
        *,
        message_id_header: str = "",
    ):
        attempts.append(to_address)
        original_send_email(
            service,
            to_address,
            subject,
            body,
            html_body,
            message_id_header=message_id_header,
        )
        raise BrokenPipeError("broken pipe")

    monkeypatch.setattr(main, "send_email", send_then_break)

    result = main.run_job(config, service)
    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines() if line.strip()]

    assert result["status"] == "completed"
    assert result["sent_recipients"] == 1
    assert result["failed_recipient_count"] == 0
    assert attempts == ["cached@example.com"]
    assert len(service.sent_messages) == 1
    assert any(entry["event"] == "delivery_recipient_send_verified_after_error" for entry in events)


def test_cached_delivery_skips_duplicate_send_when_message_already_exists(monkeypatch, tmp_path, capsys):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["cached@example.com"],
                "digest_subject": "Cached Daily Digest",
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_cached_newsletter(repository, "2026-03-24")
    service = FakeGmailService(messages=[])

    first_result = main.run_job(config, service)
    first_captured = capsys.readouterr()
    first_events = [json.loads(line) for line in first_captured.out.splitlines() if line.strip()]

    second_result = main.run_job(config, service)
    second_captured = capsys.readouterr()
    second_events = [json.loads(line) for line in second_captured.out.splitlines() if line.strip()]

    assert first_result["status"] == "completed"
    assert second_result["status"] == "completed"
    assert len(service.sent_messages) == 1
    assert any(entry["event"] == "delivery_recipient_send_completed" for entry in first_events)
    assert any(entry["event"] == "delivery_recipient_send_skipped_existing" for entry in second_events)


def test_dry_run_recipient_without_db_profile_uses_default_personalization(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")
    sources = importlib.import_module("curator.sources")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "persona": {"text": "Generalist tech reader."},
            "email": {
                "digest_recipients": ["fallback@example.com"],
                "digest_subject": "Personalized Digest",
            },
            "persona": {"text": "Generalist tech reader."},
            "additional_sources": {"enabled": True, "hours": 48},
            "limits": {
                "select_top_stories": 1,
                "final_top_stories": 1,
                "source_quotas": {"gmail": 0, "additional_source": 1},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)
    monkeypatch.setattr(sources, "datetime", FixedDateTime)

    config = main.load_config()
    repository = get_repository_from_config(config)

    recent_base = FixedDateTime.now(UTC) - timedelta(hours=2)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    _seed_story(
        repository,
        ingestion_run_id=ingestion_run_id,
        source_name="Macro Wire",
        subject="[markets] Rates reset",
        url="https://example.com/markets/rates-reset",
        anchor_text="Rates reset changes software valuations",
        context="Repository context for rates reset",
        category="Markets / stocks / macro / economy",
        article_text="Rates reset changes software valuations and reprices growth.",
        summary_body="Rates reset changes software valuations and reprices growth names.",
        published_at=recent_base.isoformat(),
        summarized_at=(recent_base + timedelta(minutes=5)).isoformat(),
    )
    _seed_story(
        repository,
        ingestion_run_id=ingestion_run_id,
        source_name="Chip Insider",
        subject="[ai] Model pricing shifted inference budgets",
        url="https://example.com/ai/model-pricing",
        anchor_text="Model pricing shifted inference budgets",
        context="Repository context for pricing",
        category="AI & ML industry developments",
        article_text="Model pricing shifted inference budgets for buyers.",
        summary_body="Model pricing shifted inference budgets for buyers evaluating serving costs.",
        published_at=(recent_base - timedelta(minutes=30)).isoformat(),
        summarized_at=(recent_base - timedelta(minutes=25)).isoformat(),
    )

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

    result = main.run_job(
        config,
        FakeGmailService(messages=[]),
        recipient_override="dry-run@example.com",
    )

    assert result["status"] == "completed"
    assert result["recipient_source"] == "dry_run_override"
    assert result["cached_newsletter"] is False
    assert result["sent_recipients"] == 1
    assert result["delivery_subscribers"] == [
        {
            "email": "dry-run@example.com",
            "persona_text": "Generalist tech reader.",
            "preferred_sources": [],
            "profile_key": result["delivery_subscribers"][0]["profile_key"],
        }
    ]
    assert [message["to"] for message in sent_messages] == ["dry-run@example.com"]
    assert "Rates reset changes software valuations" in sent_messages[0]["body"]
