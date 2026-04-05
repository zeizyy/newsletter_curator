from __future__ import annotations

import importlib
import re
from datetime import UTC, datetime, timedelta

from curator.jobs import get_repository_from_config
from tests.fakes import FakeGmailService, FakeOpenAI
from tests.helpers import create_completed_ingestion_run, write_temp_config


def _seed_ranked_stories(repository) -> None:
    now_utc = datetime.now(UTC)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    repository.upsert_article_snapshot(
        repository.upsert_story(
            {
                "source_type": "additional_source",
                "source_name": "Macro Wire",
                "subject": "[markets] Rates reset",
                "url": "https://example.com/markets/rates-reset",
                "anchor_text": "Rates reset changes software valuations",
                "context": "Repository context for rates reset",
                "category": "Markets / stocks / macro / economy",
                "published_at": (now_utc - timedelta(hours=2)).isoformat(),
                "summary": "Rates reset summary",
            },
            ingestion_run_id=ingestion_run_id,
        ),
        "Rates reset changes software valuations and reprices growth names.",
        summary_headline="Rates reset changes software valuations",
        summary_body="Key takeaways\n- Rates reset changes software valuations.\n\nWhy this matters to me\nThis matters for software multiples.",
        summary_model="gpt-5-mini",
        summarized_at="2026-03-21T08:00:00+00:00",
    )
    repository.upsert_article_snapshot(
        repository.upsert_story(
            {
                "source_type": "additional_source",
                "source_name": "AI Wire",
                "subject": "[ai] Open model pricing changed",
                "url": "https://example.com/ai/model-pricing",
                "anchor_text": "Open model pricing changed",
                "context": "Repository context for pricing",
                "category": "AI & ML industry developments",
                "published_at": (now_utc - timedelta(hours=3)).isoformat(),
                "summary": "Pricing summary",
            },
            ingestion_run_id=ingestion_run_id,
        ),
        "Open model pricing changed and pushes buyers to recalculate inference budgets.",
        summary_headline="Open model pricing changed",
        summary_body="Key takeaways\n- Open model pricing changed.\n\nWhy this matters to me\nThis matters for inference budgets.",
        summary_model="gpt-5-mini",
        summarized_at="2026-03-21T08:05:00+00:00",
    )


def _run_delivery(monkeypatch, tmp_path, *, tracking_overrides: dict, public_base_url: str = "") -> tuple[dict, list[dict], object]:
    main = importlib.import_module("main")
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "tracking": tracking_overrides,
            "email": {
                "digest_recipients": ["reader@example.com"],
                "digest_subject": "Tracked Digest",
            },
            "additional_sources": {"enabled": True, "hours": 48},
            "limits": {
                "select_top_stories": 2,
                "final_top_stories": 2,
                "source_quotas": {"gmail": 0, "additional_source": 2},
            },
        },
    )
    if public_base_url:
        monkeypatch.setenv("CURATOR_PUBLIC_BASE_URL", public_base_url)
    else:
        monkeypatch.delenv("CURATOR_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_ranked_stories(repository)

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

    monkeypatch.setattr(main, "OpenAI", lambda: FakeOpenAI())
    monkeypatch.setattr(main, "send_email", fake_send_email)
    result = main.run_job(config, FakeGmailService(messages=[]))
    return result, sent_messages, repository


def test_delivery_uses_configured_public_host_for_settings_and_tracking(monkeypatch, tmp_path):
    result, sent_messages, repository = _run_delivery(
        monkeypatch,
        tmp_path,
        tracking_overrides={"enabled": True, "open_enabled": True, "click_enabled": True},
        public_base_url="https://curator.example.com",
    )

    assert result["status"] == "completed"
    assert len(sent_messages) == 1

    body = sent_messages[0]["body"]
    html = sent_messages[0]["html_body"]

    assert body.startswith("Manage your settings: https://curator.example.com/settings\n\n")
    settings_match = re.search(r'href="https://curator\.example\.com/settings"', html)
    tracked_match = re.search(r'href="(https://curator\.example\.com/track/click/[^"]+)"', html)
    open_match = re.search(r'src="(https://curator\.example\.com/track/open/[^"]+\.gif)"', html)

    assert settings_match is not None
    assert tracked_match is not None
    assert open_match is not None
    assert settings_match.start() < tracked_match.start()

    counts = repository.get_table_counts()
    assert counts["newsletter_telemetry"] == 1
    assert counts["tracked_links"] == 2


def test_delivery_skips_tracking_when_public_host_is_unconfigured(monkeypatch, tmp_path):
    monkeypatch.delenv("CURATOR_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("CURATOR_APP_HOST", "0.0.0.0")
    monkeypatch.setenv("CURATOR_APP_PORT", "8080")

    result, sent_messages, repository = _run_delivery(
        monkeypatch,
        tmp_path,
        tracking_overrides={"enabled": True, "open_enabled": True, "click_enabled": True},
    )

    assert result["status"] == "completed"
    assert len(sent_messages) == 1

    body = sent_messages[0]["body"]
    html = sent_messages[0]["html_body"]

    assert not body.startswith("Manage your settings:")
    assert "/track/open/" not in html
    assert "/track/click/" not in html
    assert "127.0.0.1" not in html
    assert "0.0.0.0" not in html
    assert 'href="https://example.com/markets/rates-reset"' in html

    counts = repository.get_table_counts()
    assert counts["newsletter_telemetry"] == 0
    assert counts["tracked_links"] == 0
