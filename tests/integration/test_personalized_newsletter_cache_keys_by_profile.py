from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from curator.jobs import current_newsletter_date, get_repository_from_config
from tests.fakes import FakeGmailService
from tests.helpers import create_completed_ingestion_run, write_temp_config


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


def test_personalized_newsletter_cache_keys_by_profile(monkeypatch, tmp_path):
    main = importlib.import_module("main")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "persona": {"text": "Generalist tech reader."},
            "email": {
                "digest_recipients": [
                    "macro-one@example.com",
                    "macro-two@example.com",
                    "chips@example.com",
                ],
                "digest_subject": "Personalized Digest",
            },
            "subscribers": [
                {
                    "email": "macro-one@example.com",
                    "persona": {"text": "Macro investor focused on rates and valuations."},
                },
                {
                    "email": "macro-two@example.com",
                    "persona": {"text": "Macro investor focused on rates and valuations."},
                },
                {
                    "email": "chips@example.com",
                    "persona": {"text": "AI infrastructure builder focused on model costs and chips."},
                    "preferred_sources": ["Chip Insider"],
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

    config = main.load_config()
    repository = get_repository_from_config(config)
    newsletter_date = current_newsletter_date()
    default_newsletter_id = repository.upsert_daily_newsletter(
        newsletter_date=newsletter_date,
        audience_key="default",
        subject="Default Digest",
        body="Default digest body",
        html_body="<html><body>Default digest body</body></html>",
        selected_items=[{"title": "Default Story", "url": "https://example.com/default"}],
    )

    recent_base = datetime.now(UTC) - timedelta(hours=2)
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

    first_sent_messages: list[dict] = []

    def first_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        first_sent_messages.append(
            {
                "to": to_address,
                "subject": subject,
                "body": body,
                "html_body": html_body or "",
            }
        )

    monkeypatch.setattr(main, "send_email", first_send_email)

    first_result = main.run_job(config, FakeGmailService(messages=[]))

    assert first_result["status"] == "completed"
    assert first_result["personalized_delivery"] is True
    assert first_result["cached_newsletter"] is False
    assert len(first_result["delivery_groups"]) == 2
    assert all(group["cached_newsletter"] is False for group in first_result["delivery_groups"])

    all_newsletters = repository.list_daily_newsletters(include_all_audiences=True, limit=10)
    same_day_newsletters = [
        row for row in all_newsletters if row["newsletter_date"] == newsletter_date
    ]
    assert len(same_day_newsletters) == 3
    assert repository.get_daily_newsletter(newsletter_date)["id"] == default_newsletter_id
    assert repository.get_daily_newsletter(newsletter_date)["body"] == "Default digest body"

    groups_by_recipients = {
        tuple(group["recipients"]): group
        for group in first_result["delivery_groups"]
    }
    macro_group = groups_by_recipients[("macro-one@example.com", "macro-two@example.com")]
    chips_group = groups_by_recipients[("chips@example.com",)]

    assert macro_group["audience_key"] == macro_group["profile_key"]
    assert chips_group["audience_key"] == chips_group["profile_key"]
    assert macro_group["daily_newsletter_id"] != chips_group["daily_newsletter_id"]
    assert macro_group["sent_recipients"] == 2
    assert chips_group["sent_recipients"] == 1
    assert macro_group["digest_body"] != chips_group["digest_body"]

    with repository.connect() as connection:
        connection.execute("DELETE FROM fetched_stories")
        connection.execute("DELETE FROM article_snapshots")

    def fail_if_uncached(*args, **kwargs):
        raise AssertionError("Personalized cache reuse should prevent fresh candidate collection.")

    second_sent_messages: list[dict] = []

    def second_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        second_sent_messages.append(
            {
                "to": to_address,
                "subject": subject,
                "body": body,
                "html_body": html_body or "",
            }
        )

    monkeypatch.setattr(main, "collect_additional_source_links", fail_if_uncached)
    monkeypatch.setattr(main, "collect_gmail_links", fail_if_uncached)
    monkeypatch.setattr(main, "send_email", second_send_email)

    second_result = main.run_job(config, FakeGmailService(messages=[]))

    assert second_result["status"] == "completed"
    assert second_result["personalized_delivery"] is True
    assert second_result["cached_newsletter"] is True
    assert len(second_result["delivery_groups"]) == 2
    assert all(group["cached_newsletter"] is True for group in second_result["delivery_groups"])

    second_groups_by_recipients = {
        tuple(group["recipients"]): group
        for group in second_result["delivery_groups"]
    }
    assert (
        second_groups_by_recipients[("macro-one@example.com", "macro-two@example.com")]["daily_newsletter_id"]
        == macro_group["daily_newsletter_id"]
    )
    assert (
        second_groups_by_recipients[("chips@example.com",)]["daily_newsletter_id"]
        == chips_group["daily_newsletter_id"]
    )

    second_messages_by_recipient = {
        message["to"]: message for message in second_sent_messages
    }
    first_messages_by_recipient = {
        message["to"]: message for message in first_sent_messages
    }
    assert second_messages_by_recipient["macro-one@example.com"]["body"] == first_messages_by_recipient["macro-one@example.com"]["body"]
    assert second_messages_by_recipient["macro-two@example.com"]["body"] == first_messages_by_recipient["macro-two@example.com"]["body"]
    assert second_messages_by_recipient["chips@example.com"]["body"] == first_messages_by_recipient["chips@example.com"]["body"]
