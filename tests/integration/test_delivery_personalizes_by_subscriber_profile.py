from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from curator.jobs import get_repository_from_config
from tests.fakes import FakeGmailService
from tests.helpers import create_completed_ingestion_run, write_temp_config


def _seed_cached_newsletter(repository, newsletter_date: str) -> None:
    repository.upsert_daily_newsletter(
        newsletter_date=newsletter_date,
        subject="Cached Daily Digest",
        body="This cached body should be bypassed for personalized delivery.",
        html_body="<html><body><p>cached</p></body></html>",
        content={"render_groups": {}},
        selected_items=[],
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


def test_legacy_delivery_still_reuses_cached_newsletter(monkeypatch, tmp_path):
    main = importlib.import_module("main")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["legacy@example.com"],
                "digest_subject": "Legacy Digest",
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))

    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_cached_newsletter(repository, datetime.now(UTC).date().isoformat())

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
    assert result["recipient_source"] == "config"
    assert result["sent_recipients"] == 1
    assert "delivery_groups" not in result
    assert sent_messages[0]["body"].startswith(
        "This cached body should be bypassed for personalized delivery."
    )
    assert "buttondown.com/zeizyynewsletter" not in sent_messages[0]["body"]


def test_delivery_personalizes_by_subscriber_profile(monkeypatch, tmp_path):
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
    _seed_cached_newsletter(repository, datetime.now(UTC).date().isoformat())
    macro_one = repository.upsert_subscriber("macro-one@example.com")
    repository.upsert_subscriber_profile(
        int(macro_one["id"]),
        persona_text="Macro investor focused on rates and valuations.",
    )
    macro_two = repository.upsert_subscriber("macro-two@example.com")
    repository.upsert_subscriber_profile(
        int(macro_two["id"]),
        persona_text="Macro investor focused on rates and valuations.",
    )
    chips = repository.upsert_subscriber("chips@example.com")
    repository.upsert_subscriber_profile(
        int(chips["id"]),
        persona_text="AI infrastructure builder focused on model costs and chips.",
        preferred_sources=["chip insider", "CHIP insider"],
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
    assert result["personalized_delivery"] is True
    assert result["cached_newsletter"] is False
    assert result["recipient_source"] == "config"
    assert result["sent_recipients"] == 3
    assert len(result["delivery_groups"]) == 2
    assert result["delivery_subscribers"] == [
        {
            "email": "macro-one@example.com",
            "persona_text": "Macro investor focused on rates and valuations.",
            "preferred_sources": [],
            "profile_key": result["delivery_subscribers"][0]["profile_key"],
        },
        {
            "email": "macro-two@example.com",
            "persona_text": "Macro investor focused on rates and valuations.",
            "preferred_sources": [],
            "profile_key": result["delivery_subscribers"][1]["profile_key"],
        },
        {
            "email": "chips@example.com",
            "persona_text": "AI infrastructure builder focused on model costs and chips.",
            "preferred_sources": ["chip insider"],
            "profile_key": result["delivery_subscribers"][2]["profile_key"],
        },
    ]

    group_by_profile = {
        tuple(group["recipients"]): group
        for group in result["delivery_groups"]
    }
    macro_group = group_by_profile[("macro-one@example.com", "macro-two@example.com")]
    chips_group = group_by_profile[("chips@example.com",)]

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
    assert "This cached body should be bypassed for personalized delivery." not in macro_one_body


def test_personalized_delivery_reports_partial_failure(monkeypatch, tmp_path):
    main = importlib.import_module("main")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "email": {
                "digest_recipients": [
                    "macro@example.com",
                    "missing@example.com",
                ],
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

    config = main.load_config()
    repository = get_repository_from_config(config)
    macro_subscriber = repository.upsert_subscriber("macro@example.com")
    repository.upsert_subscriber_profile(
        int(macro_subscriber["id"]),
        persona_text="Macro investor focused on rates and valuations.",
    )
    missing_subscriber = repository.upsert_subscriber("missing@example.com")
    repository.upsert_subscriber_profile(
        int(missing_subscriber["id"]),
        preferred_sources=["No Such Source"],
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
    assert result["sent_recipients"] == 2
    assert {group["status"] for group in result["delivery_groups"]} == {"completed"}
    assert {message["to"] for message in sent_messages} == {
        "macro@example.com",
        "missing@example.com",
    }
