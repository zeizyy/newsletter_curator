from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from curator.jobs import NEWSLETTER_SIGNUP_CTA_URL, get_repository_from_config
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


def _seed_two_story_catalog(repository) -> None:
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


def test_delivery_prefers_db_backed_profiles_over_legacy_personalization_inputs(monkeypatch, tmp_path):
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
                "digest_recipients": ["yaml-fallback@example.com"],
                "digest_subject": "Personalized Digest",
            },
            "subscribers": [
                {
                    "email": "db-profile@example.com",
                    "persona": {"text": "YAML macro persona should lose."},
                    "preferred_sources": ["Macro Wire"],
                },
                {
                    "email": "db-blank@example.com",
                    "persona": {"text": "YAML persona should lose to blank DB profile."},
                    "preferred_sources": ["Macro Wire"],
                },
                {
                    "email": "yaml-fallback@example.com",
                    "persona": {"text": "YAML macro persona should also lose to Buttondown metadata."},
                    "preferred_sources": ["Macro Wire"],
                },
            ],
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
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "test-buttondown-key")

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_two_story_catalog(repository)

    db_profile_subscriber = repository.upsert_subscriber("db-profile@example.com")
    repository.upsert_subscriber_profile(
        int(db_profile_subscriber["id"]),
        persona_text="AI infrastructure builder focused on model costs and chips.",
        preferred_sources=["Chip Insider"],
    )
    db_blank_subscriber = repository.upsert_subscriber("db-blank@example.com")
    repository.upsert_subscriber_profile(
        int(db_blank_subscriber["id"]),
        persona_text="",
        preferred_sources=["Chip Insider"],
    )

    def fake_buttondown_get(url: str, *, headers: dict, params, timeout: int):
        assert headers == {
            "Authorization": "Token test-buttondown-key",
            "X-API-Version": "2025-06-01",
        }
        assert timeout == 15
        assert url == "https://api.buttondown.com/v1/subscribers"
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {
                "results": [
                    {
                        "email_address": "db-profile@example.com",
                        "metadata": {"persona": "Macro investor metadata that should lose."},
                    },
                    {
                        "email_address": "db-blank@example.com",
                        "metadata": {"persona": "Buttondown persona should lose to blank DB row."},
                    },
                    {
                        "email_address": "yaml-fallback@example.com",
                        "metadata": {"persona": "Macro investor focused on rates and valuations."},
                    },
                ],
                "next": None,
            },
        )

    monkeypatch.setattr(jobs.requests, "get", fake_buttondown_get)

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
    assert result["recipient_source"] == "buttondown"
    assert result["personalized_delivery"] is True
    assert result["sent_recipients"] == 3

    subscribers_by_email = {
        subscriber["email"]: subscriber
        for subscriber in result["delivery_subscribers"]
    }
    assert subscribers_by_email["db-profile@example.com"]["persona_text"] == (
        "AI infrastructure builder focused on model costs and chips."
    )
    assert subscribers_by_email["db-profile@example.com"]["preferred_sources"] == ["Chip Insider"]
    assert subscribers_by_email["db-blank@example.com"]["persona_text"] == (
        "Generalist tech reader."
    )
    assert subscribers_by_email["db-blank@example.com"]["preferred_sources"] == ["Chip Insider"]
    assert subscribers_by_email["yaml-fallback@example.com"]["persona_text"] == "Generalist tech reader."
    assert subscribers_by_email["yaml-fallback@example.com"]["preferred_sources"] == []

    messages_by_recipient = {message["to"]: message for message in sent_messages}
    assert "Model pricing shifted inference budgets" in messages_by_recipient["db-profile@example.com"]["body"]
    assert "Rates reset changes software valuations" not in messages_by_recipient["db-profile@example.com"]["body"]
    assert "Model pricing shifted inference budgets" in messages_by_recipient["db-blank@example.com"]["body"]
    assert "Rates reset changes software valuations" not in messages_by_recipient["db-blank@example.com"]["body"]
    assert "Rates reset changes software valuations" in messages_by_recipient["yaml-fallback@example.com"]["body"]
    assert "Model pricing shifted inference budgets" not in messages_by_recipient["yaml-fallback@example.com"]["body"]
    for message in sent_messages:
        assert message["body"].count(NEWSLETTER_SIGNUP_CTA_URL) == 1


def test_dry_run_recipient_override_prefers_db_profile_without_buttondown_personalization(monkeypatch, tmp_path):
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
    _seed_two_story_catalog(repository)

    subscriber = repository.upsert_subscriber("dry-run@example.com")
    repository.upsert_subscriber_profile(
        int(subscriber["id"]),
        persona_text="AI infrastructure builder focused on model costs and chips.",
        preferred_sources=["Chip Insider"],
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
    assert result["personalized_delivery"] is True
    assert result["delivery_subscribers"] == [
        {
            "email": "dry-run@example.com",
            "persona_text": "AI infrastructure builder focused on model costs and chips.",
            "preferred_sources": ["Chip Insider"],
            "profile_key": result["delivery_subscribers"][0]["profile_key"],
        }
    ]
    assert [message["to"] for message in sent_messages] == ["dry-run@example.com"]
    assert "Model pricing shifted inference budgets" in sent_messages[0]["body"]
    assert "Rates reset changes software valuations" not in sent_messages[0]["body"]
    assert sent_messages[0]["body"].count(NEWSLETTER_SIGNUP_CTA_URL) == 1
