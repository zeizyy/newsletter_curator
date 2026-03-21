from __future__ import annotations

import importlib

from curator.jobs import get_repository_from_config
from tests.fakes import FakeGmailService, FakeOpenAI
from tests.helpers import create_completed_ingestion_run, write_temp_config


def build_admin_form(config: dict, enabled_source_ids: set[int]) -> dict[str, str]:
    form = {
        "gmail_label": config["gmail"]["label"],
        "gmail_query_time_window": config["gmail"]["query_time_window"],
        "openai_reasoning_model": config["openai"]["reasoning_model"],
        "openai_summary_model": config["openai"]["summary_model"],
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


def test_admin_source_selection_filters_delivery(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["admin-filter@example.com"],
                "digest_subject": "Admin Filter Digest",
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
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Macro Wire",
            "subject": "[markets] Rates reset",
            "url": "https://example.com/markets/rates-reset",
            "anchor_text": "Rates reset changes software valuations",
            "context": "Repository context for rates reset",
            "category": "Markets / stocks / macro / economy",
            "published_at": "2026-03-21T07:30:00+00:00",
            "summary": "Rates reset summary",
        },
        ingestion_run_id=ingestion_run_id,
    )
    macro_story = repository.list_stories(source_name="Macro Wire")[0]
    repository.upsert_article_snapshot(
        int(macro_story["id"]),
        "Rates reset changes software valuations and reprices growth.",
    )
    repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "AI Wire",
            "subject": "[ai] Open model pricing changed",
            "url": "https://example.com/ai/model-pricing",
            "anchor_text": "Open model pricing changed",
            "context": "Repository context for pricing",
            "category": "AI & ML industry developments",
            "published_at": "2026-03-21T06:00:00+00:00",
            "summary": "Pricing summary",
        },
        ingestion_run_id=ingestion_run_id,
    )
    ai_story = repository.list_stories(source_name="AI Wire")[0]
    repository.upsert_article_snapshot(
        int(ai_story["id"]),
        "Open model pricing changed and pushes buyers to recalculate inference budgets.",
    )
    sources = repository.list_sources_with_selection()
    source_id_by_name = {row["source_name"]: row["id"] for row in sources}

    client = admin_app.app.test_client()
    response = client.post(
        "/",
        data=build_admin_form(config, enabled_source_ids={source_id_by_name["Macro Wire"]}),
        follow_redirects=True,
    )
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Saved" in page

    selections = repository.list_sources_with_selection()
    selection_map = {row["source_name"]: row["enabled"] for row in selections}
    assert selection_map == {"AI Wire": False, "Macro Wire": True}

    service = FakeGmailService(messages=[])
    fake_openai = FakeOpenAI()
    sent_messages: list[dict] = []

    def fail_live_article_fetch(*args, **kwargs):
        raise AssertionError("Delivery should not fetch article text live for repository stories.")

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
    monkeypatch.setattr(main, "fetch_article_text", fail_live_article_fetch)
    monkeypatch.setattr(main, "send_email", fake_send_email)

    main.run_job(config, service)

    assert len(sent_messages) == 1
    payload = sent_messages[0]
    assert payload["subject"] == "Admin Filter Digest"
    assert "Rates reset changes software valuations" in payload["body"]
    assert "Open model pricing changed" not in payload["body"]
