from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

import requests

from curator.jobs import get_repository_from_config
from tests.fakes import FakeGmailService
from tests.helpers import write_temp_config


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 24, 18, 0, 0, tzinfo=tz or UTC)


class FakeButtondownResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self) -> dict:
        return self._payload


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


def test_delivery_uses_buttondown_subscribers_before_yaml(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["fallback@example.com"],
                "digest_subject": "Cached Daily Digest",
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "test-buttondown-key")

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_cached_newsletter(repository, "2026-03-24")

    seen_calls: list[dict] = []

    def fake_buttondown_get(url: str, *, headers: dict, params, timeout: int):
        seen_calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        assert headers == {
            "Authorization": "Token test-buttondown-key",
            "X-API-Version": "2025-06-01",
        }
        assert timeout == 15
        if url == "https://api.buttondown.com/v1/subscribers":
            assert params == [
                ("per_page", 100),
                ("-type", "blocked"),
                ("-type", "complained"),
                ("-type", "removed"),
                ("-type", "unactivated"),
                ("-type", "undeliverable"),
                ("-type", "unsubscribed"),
            ]
            return FakeButtondownResponse(
                {
                    "results": [
                        {"email_address": "buttondown-a@example.com"},
                    ],
                    "next": "https://api.buttondown.com/v1/subscribers?page=2",
                }
            )
        assert url == "https://api.buttondown.com/v1/subscribers?page=2"
        assert params is None
        return FakeButtondownResponse(
            {
                "results": [
                    {"email_address": "buttondown-b@example.com"},
                    {"email_address": ""},
                    {"email_address": "buttondown-a@example.com"},
                ],
                "next": None,
            }
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
    assert result["cached_newsletter"] is True
    assert result["recipient_source"] == "buttondown"
    assert result["sent_recipients"] == 2
    assert len(seen_calls) == 2
    assert [message["to"] for message in sent_messages] == [
        "buttondown-a@example.com",
        "buttondown-b@example.com",
    ]


def test_delivery_uses_buttondown_metadata_persona_for_personalization(monkeypatch, tmp_path):
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
            "subscribers": [
                {
                    "email": "macro-one@example.com",
                    "persona": {"text": "AI infrastructure builder focused on model costs and chips."},
                },
                {
                    "email": "macro-two@example.com",
                    "persona": {"text": "AI infrastructure builder focused on model costs and chips."},
                },
                {
                    "email": "chips@example.com",
                    "persona": {"text": "Macro investor focused on rates and valuations."},
                    "preferred_sources": [" chip insider ", "CHIP insider"],
                },
            ],
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
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "test-buttondown-key")

    config = main.load_config()
    repository = get_repository_from_config(config)

    recent_base = FixedDateTime.now(UTC) - timedelta(hours=2)
    ingestion_run_id = repository.create_ingestion_run("additional_source", metadata={"test": True})
    repository.complete_ingestion_run(ingestion_run_id, status="completed", metadata={"test": True})
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
    _seed_story(
        repository,
        ingestion_run_id=ingestion_run_id,
        source_name="General Tech",
        subject="[tech] Distribution changed again",
        url="https://example.com/tech/distribution",
        anchor_text="Distribution changed again",
        context="Repository context for distribution",
        category="Company / product launches",
        article_text="Distribution changed again in consumer software.",
        summary_body="Distribution changed again in consumer software.",
        published_at=(recent_base - timedelta(minutes=60)).isoformat(),
        summarized_at=(recent_base - timedelta(minutes=55)).isoformat(),
    )

    def fake_buttondown_get(url: str, *, headers: dict, params, timeout: int):
        assert headers == {
            "Authorization": "Token test-buttondown-key",
            "X-API-Version": "2025-06-01",
        }
        assert timeout == 15
        assert url == "https://api.buttondown.com/v1/subscribers"
        assert params == [
            ("per_page", 100),
            ("-type", "blocked"),
            ("-type", "complained"),
            ("-type", "removed"),
            ("-type", "unactivated"),
            ("-type", "undeliverable"),
            ("-type", "unsubscribed"),
        ]
        return FakeButtondownResponse(
            {
                "results": [
                    {
                        "email_address": "macro-one@example.com",
                        "metadata": {"persona": "Macro investor focused on rates and valuations."},
                    },
                    {
                        "email_address": "macro-two@example.com",
                        "metadata": {"persona": "Macro investor focused on rates and valuations."},
                    },
                    {
                        "email_address": "chips@example.com",
                        "metadata": {"persona": "AI infrastructure builder focused on model costs and chips."},
                    },
                ],
                "next": None,
            }
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
    assert result["cached_newsletter"] is False
    assert len(result["delivery_groups"]) == 2

    groups_by_recipients = {
        tuple(group["recipients"]): group
        for group in result["delivery_groups"]
    }
    macro_group = groups_by_recipients[("macro-one@example.com", "macro-two@example.com")]
    chips_group = groups_by_recipients[("chips@example.com",)]

    assert macro_group["sent_recipients"] == 2
    assert chips_group["sent_recipients"] == 1
    assert chips_group["preferred_sources"] == ["chip insider"]

    messages_by_recipient = {message["to"]: message for message in sent_messages}
    macro_one_body = messages_by_recipient["macro-one@example.com"]["body"]
    macro_two_body = messages_by_recipient["macro-two@example.com"]["body"]
    chips_body = messages_by_recipient["chips@example.com"]["body"]

    assert macro_one_body == macro_two_body
    assert "Rates reset changes software valuations" in macro_one_body
    assert "Model pricing shifted inference budgets" in chips_body
    assert "Rates reset changes software valuations" not in chips_body


def test_delivery_falls_back_to_yaml_when_buttondown_fetch_fails(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["fallback@example.com"],
                "digest_subject": "Cached Daily Digest",
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "test-buttondown-key")

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_cached_newsletter(repository, "2026-03-24")

    def failing_buttondown_get(url: str, *, headers: dict, params, timeout: int):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(jobs.requests, "get", failing_buttondown_get)

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
    assert result["cached_newsletter"] is True
    assert result["recipient_source"] == "config_fallback"
    assert result["sent_recipients"] == 1
    assert [message["to"] for message in sent_messages] == ["fallback@example.com"]
