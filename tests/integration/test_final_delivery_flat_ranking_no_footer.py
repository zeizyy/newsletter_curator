from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from curator.jobs import get_repository_from_config
from tests.fakes import FakeGmailService
from tests.helpers import create_completed_ingestion_run, write_temp_config


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 24, 18, 0, 0, tzinfo=tz or UTC)


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


def _seed_story_catalog(repository) -> None:
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
        source_name="AI Wire",
        subject="[ai] Open model pricing changed",
        url="https://example.com/ai/model-pricing",
        anchor_text="Open model pricing changed",
        context="Repository context for pricing",
        category="AI & ML industry developments",
        article_text="Open model pricing changed and pushes buyers to recalculate inference budgets.",
        summary_body="Open model pricing changed and pushes buyers to recalculate inference budgets.",
        published_at=(recent_base - timedelta(minutes=30)).isoformat(),
        summarized_at=(recent_base - timedelta(minutes=25)).isoformat(),
    )


def test_fresh_delivery_persists_flat_footer_free_newsletter(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")
    sources = importlib.import_module("curator.sources")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "email": {
                "digest_recipients": ["reader@example.com"],
                "digest_subject": "Daily Digest",
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
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)
    monkeypatch.setattr(sources, "datetime", FixedDateTime)

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_story_catalog(repository)

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
    stored_newsletter = repository.get_daily_newsletter("2026-03-24")

    assert result["status"] == "completed"
    assert result["cached_newsletter"] is False
    assert stored_newsletter is not None
    assert isinstance(stored_newsletter["content"]["render_groups"], list)
    assert stored_newsletter["body"].index("Rates reset changes software valuations") < stored_newsletter["body"].index(
        "Open model pricing changed"
    )
    assert "Markets / stocks / macro / economy" not in stored_newsletter["body"]
    assert "AI & ML industry developments" not in stored_newsletter["body"]
    assert "buttondown.com/zeizyynewsletter" not in stored_newsletter["body"]
    assert "subscribe to AI Signal Daily" not in stored_newsletter["html_body"]
    assert "category-title" not in stored_newsletter["html_body"]
    assert "buttondown.com/zeizyynewsletter" not in stored_newsletter["html_body"]
    assert sent_messages[0]["body"] == stored_newsletter["body"]
    assert sent_messages[0]["html_body"] == stored_newsletter["html_body"]


def test_cached_delivery_keeps_flat_footer_free_output(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")
    sources = importlib.import_module("curator.sources")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "email": {
                "digest_recipients": ["reader@example.com"],
                "digest_subject": "Daily Digest",
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
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)
    monkeypatch.setattr(sources, "datetime", FixedDateTime)

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_story_catalog(repository)

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

    first_result = main.run_job(config, FakeGmailService(messages=[]))
    stored_newsletter = repository.get_daily_newsletter("2026-03-24")
    assert first_result["cached_newsletter"] is False
    assert stored_newsletter is not None

    sent_messages.clear()
    second_result = main.run_job(config, FakeGmailService(messages=[]))

    assert second_result["status"] == "completed"
    assert second_result["cached_newsletter"] is True
    assert sent_messages[0]["body"] == stored_newsletter["body"]
    assert sent_messages[0]["html_body"] != ""
    assert "buttondown.com/zeizyynewsletter" not in sent_messages[0]["body"]
    assert "buttondown.com/zeizyynewsletter" not in sent_messages[0]["html_body"]
    assert "category-title" not in sent_messages[0]["html_body"]
