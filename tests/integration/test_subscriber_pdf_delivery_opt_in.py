from __future__ import annotations

import importlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from io import BytesIO

from pypdf import PdfReader

from curator.jobs import get_repository_from_config
from curator.pdf import render_digest_pdf
from curator.repository import SQLiteRepository
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


def _create_logged_in_subscriber(admin_app_module, email_address: str):
    repository = admin_app_module.load_repository(admin_app_module.load_merged_config())
    subscriber = repository.upsert_subscriber(email_address)
    session = repository.create_subscriber_session(int(subscriber["id"]))
    return repository, subscriber, session


def test_pdf_story_rendering_does_not_duplicate_takeaways_or_draw_missing_glyphs():
    summary_raw = json.dumps(
        {
            "headline": "NVIDIA B200 spot rents surge",
            "body": (
                "Key takeaways - NVIDIA B200 rental price jumped to $4.95/hr from $2.31 "
                "in early March. - The B200 premium over prior\u2011gen H200 doubled. "
                "- GPT\u20115.5 demand widened the gap re\u2011widened in Q2 2026.\n\n"
                "Why this matters to me Rising B200 rents mean higher inference costs."
            ),
            "key_takeaways": [
                "NVIDIA B200 rental price jumped to $4.95/hr from $2.31 in early March.",
                "The B200 premium over prior\u2011gen H200 doubled.",
                "GPT\u20115.5 demand widened the gap re\u2011widened in Q2 2026.",
            ],
            "why_this_matters": "Rising B200 rents mean higher inference costs.",
        }
    )
    pdf_bytes = render_digest_pdf(
        [
            {
                "title": "NVIDIA B200 spot rents surge",
                "summary_raw": summary_raw,
                "source_name": "GPU Market Watch",
                "published_at": "2026-04-30T14:00:00+00:00",
                "url": "https://example.com/gpu-rents",
            }
        ],
        subject="AI Signal Daily",
        newsletter_date="April 30, 2026",
    )

    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_bytes)).pages)

    assert pdf_text.lower().count("key takeaways") == 1
    assert "Key takeaways - NVIDIA" not in pdf_text
    assert "prior-gen H200" in pdf_text
    assert "GPT-5.5" in pdf_text
    assert "re-widened" in pdf_text
    assert "\u2011" not in pdf_text


def test_legacy_subscriber_profile_migrates_delivery_format_without_schema_reset(tmp_path):
    db_path = tmp_path / "curator.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_address TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE subscriber_profiles (
                subscriber_id INTEGER PRIMARY KEY REFERENCES subscribers(id) ON DELETE CASCADE,
                persona_text TEXT NOT NULL DEFAULT '',
                preferred_sources_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            INSERT INTO subscribers (id, email_address, created_at, updated_at)
            VALUES (1, 'legacy@example.com', '2026-04-04T00:00:00+00:00', '2026-04-04T00:00:00+00:00');

            INSERT INTO subscriber_profiles (
                subscriber_id,
                persona_text,
                preferred_sources_json,
                created_at,
                updated_at
            )
            VALUES (1, 'Legacy persona', '["Macro Wire"]', '2026-04-04T00:00:00+00:00', '2026-04-04T00:00:00+00:00');
            """
        )

    repository = SQLiteRepository(db_path)
    repository.initialize()
    profile = repository.get_subscriber_profile(1)

    assert profile["persona_text"] == "Legacy persona"
    assert profile["delivery_format"] == "email"
    assert profile["preferred_sources"] == ["Macro Wire"]

    with repository.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(subscriber_profiles)").fetchall()
        }

    assert "delivery_format" in columns


def test_subscriber_settings_page_can_persist_pdf_delivery_format(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))

    repository, subscriber, session = _create_logged_in_subscriber(admin_app, "kindle@example.com")
    repository.upsert_subscriber_profile(int(subscriber["id"]), delivery_format="email")

    client = admin_app.app.test_client()
    client.set_cookie(admin_app.SUBSCRIBER_SESSION_COOKIE, session["token"])

    response = client.post(
        "/settings",
        data={"persona_text": "", "pdf_delivery_enabled": "1"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Add a PDF copy" in page
    assert "Add PDF attachment" in page
    assert 'name="pdf_delivery_enabled"' in page

    profile = repository.get_subscriber_profile(int(subscriber["id"]))
    assert profile["delivery_format"] == "pdf"


def test_mixed_email_and_pdf_delivery_routes_correctly(monkeypatch, tmp_path, capsys):
    main = importlib.import_module("main")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "persona": {"text": "Generalist tech reader."},
            "email": {
                "digest_recipients": [
                    "reader@example.com",
                    "kindle@example.com",
                ],
                "digest_subject": "Portable Digest",
            },
            "tracking": {"enabled": True, "open_enabled": True, "click_enabled": True},
            "additional_sources": {"enabled": True, "hours": 48},
            "limits": {
                "select_top_stories": 2,
                "final_top_stories": 2,
                "source_quotas": {"gmail": 0, "additional_source": 2},
            },
        },
    )
    monkeypatch.setenv("CURATOR_PUBLIC_BASE_URL", "https://curator.example.com")
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))

    config = main.load_config()
    repository = get_repository_from_config(config)

    email_subscriber = repository.upsert_subscriber("reader@example.com")
    repository.upsert_subscriber_profile(int(email_subscriber["id"]), delivery_format="email")
    pdf_subscriber = repository.upsert_subscriber("kindle@example.com")
    repository.upsert_subscriber_profile(int(pdf_subscriber["id"]), delivery_format="pdf")

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

    sent_messages: list[dict] = []

    def fake_send_email(
        service,
        to_address: str,
        subject: str,
        body: str,
        html_body: str | None = None,
        *,
        attachments: list[dict] | None = None,
    ):
        sent_messages.append(
            {
                "to": to_address,
                "subject": subject,
                "body": body,
                "html_body": html_body or "",
                "attachments": list(attachments or []),
            }
        )

    monkeypatch.setattr(main, "send_email", fake_send_email)

    result = main.run_job(config, FakeGmailService(messages=[]), issue_type_override="daily")
    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines() if line.strip()]

    assert result["status"] == "completed"
    assert result["personalized_delivery"] is True
    assert len(result["delivery_groups"]) == 2
    assert {group["delivery_format"] for group in result["delivery_groups"]} == {"email", "pdf"}
    delivery_groups_by_format = {
        group["delivery_format"]: group
        for group in result["delivery_groups"]
    }
    assert delivery_groups_by_format["email"]["audience_key"] == delivery_groups_by_format["pdf"]["audience_key"]
    assert delivery_groups_by_format["email"]["daily_newsletter_id"] == delivery_groups_by_format["pdf"]["daily_newsletter_id"]
    assert delivery_groups_by_format["email"]["cached_newsletter"] is False
    assert delivery_groups_by_format["pdf"]["cached_newsletter"] is True
    assert result["delivery_subscribers"] == [
        {
            "email": "reader@example.com",
            "persona_text": "Generalist tech reader.",
            "delivery_format": "email",
            "preferred_sources": [],
            "profile_key": result["delivery_subscribers"][0]["profile_key"],
        },
        {
            "email": "kindle@example.com",
            "persona_text": "Generalist tech reader.",
            "delivery_format": "pdf",
            "preferred_sources": [],
            "profile_key": result["delivery_subscribers"][1]["profile_key"],
        },
    ]

    messages_by_recipient = {message["to"]: message for message in sent_messages}
    email_message = messages_by_recipient["reader@example.com"]
    pdf_message = messages_by_recipient["kindle@example.com"]

    assert "Rates reset changes software valuations" in email_message["body"]
    assert "Model pricing shifted inference budgets" in email_message["body"]
    assert email_message["html_body"] != ""
    assert email_message["attachments"] == []
    assert "/track/click/" in email_message["html_body"]
    assert "/track/open/" in email_message["html_body"]

    assert "Rates reset changes software valuations" in pdf_message["body"]
    assert "Model pricing shifted inference budgets" in pdf_message["body"]
    assert pdf_message["html_body"] != ""
    assert len(pdf_message["attachments"]) == 1
    assert "/track/click/" in pdf_message["html_body"]
    assert "/track/open/" in pdf_message["html_body"]
    pdf_attachment = pdf_message["attachments"][0]
    assert pdf_attachment["mime_type"] == "application/pdf"
    assert pdf_attachment["filename"].startswith("ai-signal-daily-")
    assert pdf_attachment["filename"].endswith(".pdf")

    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(BytesIO(pdf_attachment["content_bytes"])).pages
    )
    first_title = "Rates reset changes software valuations"
    second_title = "Model pricing shifted inference budgets"
    assert first_title in pdf_text
    assert second_title in pdf_text
    assert pdf_text.index(first_title) < pdf_text.index(second_title)

    pdf_delivery_started = next(
        entry
        for entry in events
        if entry["event"] == "delivery_started" and entry["delivery_format"] == "pdf"
    )
    email_delivery_started = next(
        entry
        for entry in events
        if entry["event"] == "delivery_started" and entry["delivery_format"] == "email"
    )
    assert email_delivery_started["cached_newsletter_available"] is False
    assert pdf_delivery_started["cached_newsletter_available"] is True
    assert email_delivery_started["audience_key"] == pdf_delivery_started["audience_key"]
    assert pdf_delivery_started["telemetry_enabled"] is True
    assert pdf_delivery_started["open_tracking_enabled"] is True
    assert pdf_delivery_started["click_tracking_enabled"] is True

    pdf_tracking_prepared = next(
        entry
        for entry in events
        if entry["event"] == "delivery_tracking_prepared" and entry["audience_key"] == pdf_delivery_started["audience_key"]
    )
    assert pdf_tracking_prepared["tracked_link_count"] == 2
    assert pdf_tracking_prepared["click_tracking_enabled"] is True
