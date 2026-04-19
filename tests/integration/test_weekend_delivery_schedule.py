from __future__ import annotations

import importlib
from datetime import UTC, datetime

from curator.jobs import get_repository_from_config
from tests.fakes import FakeGmailService
from tests.helpers import create_completed_ingestion_run, write_temp_config


class FixedSaturdayDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 28, 18, 0, 0, tzinfo=tz or UTC)


class FixedSundayDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 29, 18, 0, 0, tzinfo=tz or UTC)


class FixedMondayDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 30, 18, 0, 0, tzinfo=tz or UTC)


class FixedUtcSundayPacificSaturdayDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        current = cls(2026, 3, 29, 1, 0, 0, tzinfo=UTC)
        return current.astimezone(tz) if tz else current


def _seed_story(
    repository,
    ingestion_run_id: int,
    *,
    title: str,
    url: str,
    published_at: str,
) -> None:
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Strategy Wire",
            "subject": f"[strategy] {title}",
            "url": url,
            "anchor_text": title,
            "context": f"Repository context for {title}.",
            "category": "Tech company news & strategy",
            "published_at": published_at,
            "summary": f"{title} summary",
        },
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        f"{title} gives operators a useful signal about AI platform strategy.",
        summary_headline=title,
        summary_body=f"{title} gives operators a useful signal about AI platform strategy.",
        summary_model="gpt-5-mini",
        summarized_at=published_at,
    )


def test_saturday_delivery_sends_weekly_digest_for_past_week(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")
    sources = importlib.import_module("curator.sources")
    monkeypatch.delenv("CURATOR_IGNORE_DELIVERY_SCHEDULE", raising=False)

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "email": {
                "digest_recipients": ["weekly@example.com"],
                "digest_subject": "Daily Digest",
                "weekly_digest_subject": "Weekly Digest",
            },
            "additional_sources": {"enabled": True, "hours": 24},
            "limits": {
                "select_top_stories": 5,
                "final_top_stories": 5,
                "source_quotas": {"gmail": 0, "additional_source": 5},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedSaturdayDateTime)
    monkeypatch.setattr(sources, "datetime", FixedSaturdayDateTime)
    config = main.load_config()
    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    _seed_story(
        repository,
        ingestion_run_id,
        title="Six day old platform shift",
        url="https://example.com/weekly/in-window",
        published_at="2026-03-22T18:00:00+00:00",
    )
    _seed_story(
        repository,
        ingestion_run_id,
        title="Eight day old platform shift",
        url="https://example.com/weekly/out-of-window",
        published_at="2026-03-20T18:00:00+00:00",
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

    result = main.run_job(config, FakeGmailService(messages=[]))

    assert result["status"] == "completed"
    assert result["issue_type"] == "weekly"
    assert len(sent_messages) == 1
    assert sent_messages[0]["subject"] == "Weekly Digest"
    assert "Six day old platform shift" in sent_messages[0]["body"]
    assert "Eight day old platform shift" not in sent_messages[0]["body"]

    stored_newsletter = repository.get_daily_newsletter("2026-03-28")
    assert stored_newsletter is not None
    assert stored_newsletter["subject"] == "Weekly Digest"
    assert stored_newsletter["metadata"]["issue_type"] == "weekly"


def test_manual_weekly_digest_override_sends_past_week_outside_saturday(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")
    sources = importlib.import_module("curator.sources")
    monkeypatch.delenv("CURATOR_IGNORE_DELIVERY_SCHEDULE", raising=False)

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "email": {
                "digest_recipients": ["weekly@example.com"],
                "digest_subject": "Daily Digest",
                "weekly_digest_subject": "Weekly Digest",
            },
            "additional_sources": {"enabled": True, "hours": 24},
            "limits": {
                "select_top_stories": 5,
                "final_top_stories": 5,
                "source_quotas": {"gmail": 0, "additional_source": 5},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedMondayDateTime)
    monkeypatch.setattr(sources, "datetime", FixedMondayDateTime)
    config = main.load_config()
    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    _seed_story(
        repository,
        ingestion_run_id,
        title="Manual weekly platform shift",
        url="https://example.com/weekly/manual-in-window",
        published_at="2026-03-24T18:00:00+00:00",
    )
    _seed_story(
        repository,
        ingestion_run_id,
        title="Manual weekly stale platform shift",
        url="https://example.com/weekly/manual-out-of-window",
        published_at="2026-03-21T18:00:00+00:00",
    )

    sent_messages: list[dict] = []

    def fake_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        sent_messages.append({"to": to_address, "subject": subject, "body": body})

    monkeypatch.setattr(main, "send_email", fake_send_email)

    result = main.run_job(
        config,
        FakeGmailService(messages=[]),
        issue_type_override="weekly",
    )

    assert result["status"] == "completed"
    assert result["issue_type"] == "weekly"
    assert len(sent_messages) == 1
    assert sent_messages[0]["subject"] == "Weekly Digest"
    assert "Manual weekly platform shift" in sent_messages[0]["body"]
    assert "Manual weekly stale platform shift" not in sent_messages[0]["body"]


def test_weekly_digest_caps_candidates_to_five_stories_per_day(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")
    sources = importlib.import_module("curator.sources")
    monkeypatch.delenv("CURATOR_IGNORE_DELIVERY_SCHEDULE", raising=False)

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "email": {
                "digest_recipients": ["weekly@example.com"],
                "weekly_digest_subject": "Weekly Digest",
            },
            "additional_sources": {"enabled": True, "hours": 24},
            "limits": {
                "select_top_stories": 10,
                "final_top_stories": 10,
                "source_quotas": {"gmail": 0, "additional_source": 6},
            },
            "weekly": {"max_stories_per_day": 5},
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedSaturdayDateTime)
    monkeypatch.setattr(sources, "datetime", FixedSaturdayDateTime)
    config = main.load_config()
    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    for index in range(6):
        hour = 17 - index
        _seed_story(
            repository,
            ingestion_run_id,
            title=f"Same day platform shift {index + 1}",
            url=f"https://example.com/weekly/same-day-{index + 1}",
            published_at=f"2026-03-27T{hour:02d}:00:00+00:00",
        )

    sent_messages: list[dict] = []

    def fake_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        sent_messages.append({"to": to_address, "subject": subject, "body": body})

    monkeypatch.setattr(main, "send_email", fake_send_email)

    result = main.run_job(config, FakeGmailService(messages=[]))

    assert result["status"] == "completed"
    assert result["issue_type"] == "weekly"
    assert result["uncapped_eligible_links"] == 6
    assert result["eligible_links"] == 5
    assert result["weekly_max_stories_per_day"] == 5
    assert result["accepted_items"] == 5
    assert "Same day platform shift 1" in sent_messages[0]["body"]
    assert "Same day platform shift 5" in sent_messages[0]["body"]
    assert "Same day platform shift 6" not in sent_messages[0]["body"]

    stored_newsletter = repository.get_daily_newsletter("2026-03-28")
    assert stored_newsletter is not None
    assert stored_newsletter["metadata"]["uncapped_eligible_links"] == 6
    assert stored_newsletter["metadata"]["eligible_links"] == 5
    assert stored_newsletter["metadata"]["weekly_max_stories_per_day"] == 5


def test_delivery_weekday_decisions_use_pacific_time_at_utc_boundary(monkeypatch):
    jobs = importlib.import_module("curator.jobs")
    monkeypatch.setattr(jobs, "datetime", FixedUtcSundayPacificSaturdayDateTime)

    delivery_now = jobs.current_delivery_datetime()

    assert delivery_now.tzinfo == jobs.PACIFIC_TIMEZONE
    assert delivery_now.isoformat() == "2026-03-28T18:00:00-07:00"
    assert jobs.current_newsletter_date() == "2026-03-28"
    assert jobs.delivery_issue_type_for_datetime(
        datetime(2026, 3, 29, 1, 0, 0, tzinfo=UTC)
    ) == "weekly"
    assert jobs.delivery_issue_type_for_datetime(
        datetime(2026, 3, 31, 6, 30, 0, tzinfo=UTC)
    ) == "daily"
    assert jobs.delivery_issue_type_for_datetime(
        datetime(2026, 3, 30, 7, 30, 0, tzinfo=UTC)
    ) == "daily"


def test_sunday_delivery_is_skipped_without_alert(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")
    monkeypatch.delenv("CURATOR_IGNORE_DELIVERY_SCHEDULE", raising=False)

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["weekend@example.com"],
                "alert_recipient": "ops@example.com",
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedSundayDateTime)
    config = main.load_config()

    sent_messages: list[dict] = []

    def fake_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        sent_messages.append({"to": to_address, "subject": subject, "body": body})

    monkeypatch.setattr(main, "send_email", fake_send_email)

    result = main.run_job(config, FakeGmailService(messages=[]))
    alert_sent = main.send_delivery_failure_alert_if_needed(
        config,
        FakeGmailService(messages=[]),
        source="test",
        result=result,
    )

    assert result["status"] == "skipped"
    assert result["issue_type"] == "skipped"
    assert result["sent_recipients"] == 0
    assert sent_messages == []
    assert alert_sent is False
