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
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "test-buttondown-key")

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_cached_newsletter(repository, "2026-03-24")

    seen_calls: list[dict] = []

    def fake_buttondown_get(url: str, *, headers: dict, params, timeout: int):
        seen_calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        assert url == "https://api.buttondown.com/v1/subscribers/dry-run%40example.com"
        assert headers == {
            "Authorization": "Token test-buttondown-key",
            "X-API-Version": "2025-06-01",
        }
        assert params is None
        assert timeout == 15
        return SimpleNamespace(
            status_code=404,
            raise_for_status=lambda: None,
            json=lambda: {},
        )

    monkeypatch.setattr(jobs.requests, "get", fake_buttondown_get)
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
    assert len(seen_calls) == 1
    assert [message["to"] for message in sent_messages] == ["dry-run@example.com"]


def test_dry_run_recipient_uses_buttondown_metadata_persona(monkeypatch, tmp_path):
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
                    "email": "dry-run@example.com",
                    "persona": {"text": "AI infrastructure builder focused on model costs and chips."},
                }
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

    def fake_buttondown_get(url: str, *, headers: dict, params, timeout: int):
        assert url == "https://api.buttondown.com/v1/subscribers/dry-run%40example.com"
        assert headers == {
            "Authorization": "Token test-buttondown-key",
            "X-API-Version": "2025-06-01",
        }
        assert params is None
        assert timeout == 15
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {
                "email_address": "dry-run@example.com",
                "metadata": {"persona": "Macro investor focused on rates and valuations."},
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

    result = main.run_job(
        config,
        FakeGmailService(messages=[]),
        recipient_override="dry-run@example.com",
    )

    assert result["status"] == "completed"
    assert result["recipient_source"] == "dry_run_override"
    assert result["personalized_delivery"] is True
    assert result["cached_newsletter"] is False
    assert result["sent_recipients"] == 1
    assert [message["to"] for message in sent_messages] == ["dry-run@example.com"]
    assert "Rates reset changes software valuations" in sent_messages[0]["body"]
    assert "Model pricing shifted inference budgets" not in sent_messages[0]["body"]
