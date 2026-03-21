from __future__ import annotations

import importlib

import pytest

from curator.jobs import get_repository_from_config, run_fetch_gmail_job, run_fetch_sources_job
from tests.fakes import (
    FakeArticleFetcher,
    FakeGmailService,
    FakeOpenAI,
    FakeSourceFetcher,
    make_gmail_message,
)
from tests.helpers import write_temp_config


def build_admin_form(config: dict, enabled_source_ids: set[int]) -> dict[str, str]:
    form = {
        "gmail_label": config["gmail"]["label"],
        "gmail_query_time_window": config["gmail"]["query_time_window"],
        "openai_reasoning_model": config["openai"]["reasoning_model"],
        "openai_summary_model": config["openai"]["summary_model"],
        "persona_text": config.get("persona", {}).get("text", ""),
        "additional_enabled": "on" if config["additional_sources"]["enabled"] else "",
        "additional_script_path": config["additional_sources"]["script_path"],
        "additional_feeds_file": config["additional_sources"]["feeds_file"],
        "additional_hours": str(config["additional_sources"]["hours"]),
        "additional_top_per_category": str(config["additional_sources"]["top_per_category"]),
        "additional_max_total": str(config["additional_sources"]["max_total"]),
        "limit_max_links_per_email": str(config["limits"]["max_links_per_email"]),
        "limit_select_top_stories": str(config["limits"]["select_top_stories"]),
        "limit_max_per_category": str(config["limits"]["max_per_category"]),
        "limit_final_top_stories": str(config["limits"]["final_top_stories"]),
        "quota_gmail": str(config["limits"]["source_quotas"]["gmail"]),
        "quota_additional_source": str(config["limits"]["source_quotas"]["additional_source"]),
        "limit_max_article_chars": str(config["limits"]["max_article_chars"]),
        "limit_max_summary_workers": str(config["limits"]["max_summary_workers"]),
        "email_digest_subject": config["email"]["digest_subject"],
        "email_alert_recipient": config["email"]["alert_recipient"],
        "email_alert_subject_prefix": config["email"]["alert_subject_prefix"],
        "email_digest_recipients": "\n".join(config["email"]["digest_recipients"]),
    }
    for source_id in enabled_source_ids:
        form[f"source_enabled_{source_id}"] = "on"
    return form


def test_full_two_job_pipeline(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    gmail_html = """
    <html>
      <body>
        <a href="https://example.com/gmail/cloud-budgets">Cloud budgets reset</a>
      </body>
    </html>
    """
    gmail_service = FakeGmailService(
        messages=[
            make_gmail_message(
                message_id="gmail-1",
                subject="Infra Letter",
                from_header="Infra Letter <infra@example.com>",
                date_header="Sat, 21 Mar 2026 07:00:00 +0000",
                html_body=gmail_html,
            )
        ]
    )
    additional_source_fetcher = FakeSourceFetcher(
        [
            {
                "source_type": "additional_source",
                "source_name": "Macro Wire",
                "subject": "[markets] Rates reset",
                "url": "https://example.com/markets/rates-reset",
                "anchor_text": "Rates reset changes software valuations",
                "context": "Repository context for rates reset.",
                "category": "Markets / stocks / macro / economy",
                "published_at": "2026-03-21T07:30:00+00:00",
                "summary": "Rates reset summary",
            },
            {
                "source_type": "additional_source",
                "source_name": "AI Wire",
                "subject": "[ai] Open model pricing changed",
                "url": "https://example.com/ai/model-pricing",
                "anchor_text": "Open model pricing changed",
                "context": "Repository context for pricing.",
                "category": "AI & ML industry developments",
                "published_at": "2026-03-21T06:00:00+00:00",
                "summary": "Pricing summary",
            },
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            "https://example.com/gmail/cloud-budgets": (
                "Cloud budgets reset and infrastructure teams are reprioritizing GPU workloads."
            ),
            "https://example.com/markets/rates-reset": (
                "Rates reset changes software valuations and reprices growth."
            ),
            "https://example.com/ai/model-pricing": (
                "Open model pricing changed and pushes buyers to recalculate inference budgets."
            ),
        }
    )

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "additional_sources": {"enabled": True, "hours": 48},
            "email": {
                "digest_recipients": ["pipeline@example.com"],
                "digest_subject": "Two Job Digest",
            },
            "limits": {
                "select_top_stories": 2,
                "final_top_stories": 2,
                "source_quotas": {"gmail": 1, "additional_source": 1},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    fetch_gmail_result = run_fetch_gmail_job(
        config,
        gmail_service,
        article_fetcher=article_fetcher,
    )
    fetch_sources_result = run_fetch_sources_job(
        config,
        source_fetcher=additional_source_fetcher,
        article_fetcher=article_fetcher,
    )

    repository = get_repository_from_config(config)
    available_sources = repository.list_sources_with_selection()
    enabled_source_ids = {
        row["id"]
        for row in available_sources
        if row["source_type"] == "gmail" or row["source_name"] == "Macro Wire"
    }
    client = admin_app.app.test_client()
    response = client.post(
        "/",
        data=build_admin_form(config, enabled_source_ids=enabled_source_ids),
        follow_redirects=True,
    )
    assert response.status_code == 200

    def failing_source_fetcher(_config: dict) -> list[dict]:
        raise RuntimeError("publisher ingest timeout")

    with pytest.raises(RuntimeError):
        run_fetch_sources_job(config, source_fetcher=failing_source_fetcher)

    fake_openai = FakeOpenAI()
    sent_messages: list[dict] = []

    def fail_live_gmail_reads(*args, **kwargs):
        raise AssertionError("Delivery should not read Gmail live after repository ingest.")

    def fail_live_article_fetch(*args, **kwargs):
        raise AssertionError("Delivery should not fetch article text live.")

    def fake_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        sent_messages.append(
            {
                "to": to_address,
                "subject": subject,
                "body": body,
                "html_body": html_body or "",
            }
        )

    monkeypatch.setattr(main, "OpenAI", lambda: fake_openai)
    monkeypatch.setattr(main, "list_message_ids_for_label", fail_live_gmail_reads)
    monkeypatch.setattr(main, "get_message", fail_live_gmail_reads)
    monkeypatch.setattr(main, "fetch_article_text", fail_live_article_fetch)
    monkeypatch.setattr(main, "send_email", fake_send_email)

    delivery_service = FakeGmailService(messages=[])
    result = main.run_job(config, delivery_service)
    latest_delivery_run = repository.get_latest_delivery_run()

    assert fetch_gmail_result["status"] == "completed"
    assert fetch_sources_result["status"] == "completed"
    assert result["status"] == "completed"
    assert latest_delivery_run is not None
    assert latest_delivery_run["status"] == "completed"
    readiness = latest_delivery_run["metadata"]["readiness"]
    assert readiness["ok"] is True
    assert set(readiness["ready_source_types"]) == {"gmail", "additional_source"}
    additional_source_readiness = next(
        entry for entry in readiness["sources"] if entry["source_type"] == "additional_source"
    )
    assert additional_source_readiness["ready"] is True
    assert additional_source_readiness["latest_run_status"] == "failed"
    assert "latest_run_status=failed" in additional_source_readiness["warnings"]

    assert len(sent_messages) == 1
    payload = sent_messages[0]
    assert payload["subject"] == "Two Job Digest"
    assert payload["to"] == "pipeline@example.com"
    assert "Cloud budgets reset and infrastructure teams" in payload["body"]
    assert "Rates reset changes software valuations" in payload["body"]
    assert "Open model pricing changed" not in payload["body"]
