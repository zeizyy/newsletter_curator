from __future__ import annotations

from copy import deepcopy
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


def test_personalized_newsletter_cache_keys_by_profile(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")
    sources = importlib.import_module("curator.sources")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "email": {
                "digest_recipients": ["generic@example.com"],
                "digest_subject": "Personalized Digest",
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

    generic_config = main.load_config()
    repository = get_repository_from_config(generic_config)
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

    generic_result = main.run_job(generic_config, FakeGmailService(messages=[]))
    default_newsletter = repository.get_daily_newsletter("2026-03-24")

    assert generic_result["status"] == "completed"
    assert generic_result["cached_newsletter"] is False
    assert default_newsletter is not None
    assert default_newsletter["audience_key"] == "default"

    personalized_config = deepcopy(generic_config)
    personalized_config["email"]["digest_recipients"] = [
        "macro-one@example.com",
        "macro-two@example.com",
        "chips@example.com",
    ]
    personalized_config["subscribers"] = [
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
    ]

    sent_messages.clear()
    first_personalized = main.run_job(personalized_config, FakeGmailService(messages=[]))

    assert first_personalized["status"] == "completed"
    assert first_personalized["personalized_delivery"] is True
    assert first_personalized["cached_newsletter"] is False
    assert len(first_personalized["delivery_groups"]) == 2
    assert all(group["cached_newsletter"] is False for group in first_personalized["delivery_groups"])

    newsletters = repository.list_daily_newsletters(limit=10, include_all_audiences=True)
    newsletter_ids = {row["id"] for row in newsletters if row["newsletter_date"] == "2026-03-24"}
    audience_keys = {
        row["audience_key"] for row in newsletters if row["newsletter_date"] == "2026-03-24"
    }
    assert len(newsletter_ids) == 3
    assert "default" in audience_keys

    grouped_ids = {
        tuple(group["recipients"]): int(group["daily_newsletter_id"])
        for group in first_personalized["delivery_groups"]
    }
    assert grouped_ids[("macro-one@example.com", "macro-two@example.com")] != grouped_ids[
        ("chips@example.com",)
    ]
    assert all(
        int(group["daily_newsletter_id"]) != int(default_newsletter["id"])
        for group in first_personalized["delivery_groups"]
    )

    with repository.connect() as connection:
        connection.execute("DELETE FROM article_snapshots")
        connection.execute("DELETE FROM fetched_stories")

    def fail_fake_select(*args, **kwargs):
        raise AssertionError("Audience-aware cache should prevent reranking on the second run.")

    def fail_fake_summarize(*args, **kwargs):
        raise AssertionError("Audience-aware cache should prevent resummarization on the second run.")

    monkeypatch.setattr(main.dev, "fake_select_top_stories", fail_fake_select)
    monkeypatch.setattr(main.dev, "fake_summarize_article", fail_fake_summarize)

    sent_messages.clear()
    second_personalized = main.run_job(personalized_config, FakeGmailService(messages=[]))

    assert second_personalized["status"] == "completed"
    assert second_personalized["personalized_delivery"] is True
    assert second_personalized["cached_newsletter"] is True
    assert all(group["cached_newsletter"] is True for group in second_personalized["delivery_groups"])
    assert {
        tuple(group["recipients"]): int(group["daily_newsletter_id"])
        for group in second_personalized["delivery_groups"]
    } == grouped_ids
    assert len(sent_messages) == 3

