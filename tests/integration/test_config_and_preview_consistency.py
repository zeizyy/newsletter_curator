from __future__ import annotations

import importlib
from pathlib import Path

from werkzeug.datastructures import MultiDict
import yaml

from curator.config import DEFAULT_CONFIG, load_config


def build_admin_form(config: dict) -> MultiDict:
    return MultiDict(
        {
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
            "persona_text": str(config["persona"]["text"]),
        }
    )


def test_checked_in_config_keeps_tracking_explicit_without_public_origin():
    raw = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    config = load_config("config.yaml")

    assert "subscribers" not in raw
    assert config["additional_sources"]["max_total"] == DEFAULT_CONFIG["additional_sources"]["max_total"]
    assert config["database"]["newsletter_ttl_days"] == 7
    assert config["database"]["allow_schema_reset"] is False
    assert config["email"]["digest_subject"] == "AI Signal Daily"
    assert config["email"]["alert_recipient"] == "zeizyy@gmail.com"
    assert config["tracking"]["enabled"] is True
    assert config["tracking"]["open_enabled"] is True
    assert config["tracking"]["click_enabled"] is True
    assert "base_url" not in raw["tracking"]
    assert "base_url" not in config["tracking"]


def test_admin_form_blank_fields_use_runtime_defaults():
    admin_app = importlib.import_module("admin_app")

    form = build_admin_form(load_config("config.yaml"))
    form["additional_max_total"] = ""
    form["email_digest_subject"] = ""

    updated, errors = admin_app.update_config_from_form({}, form)

    assert errors == []
    assert updated["additional_sources"]["max_total"] == DEFAULT_CONFIG["additional_sources"]["max_total"]
    assert updated["email"]["digest_subject"] == DEFAULT_CONFIG["email"]["digest_subject"]


def test_app_host_and_port_prefer_new_env_names_with_legacy_fallback(monkeypatch):
    admin_app = importlib.import_module("admin_app")

    monkeypatch.delenv("CURATOR_APP_HOST", raising=False)
    monkeypatch.delenv("CURATOR_APP_PORT", raising=False)
    monkeypatch.setenv("CURATOR_ADMIN_HOST", "0.0.0.0")
    monkeypatch.setenv("CURATOR_ADMIN_PORT", "9090")

    assert admin_app.configured_app_host() == "0.0.0.0"
    assert admin_app.configured_app_port() == 9090

    monkeypatch.setenv("CURATOR_APP_HOST", "127.0.0.1")
    monkeypatch.setenv("CURATOR_APP_PORT", "8080")

    assert admin_app.configured_app_host() == "127.0.0.1"
    assert admin_app.configured_app_port() == 8080


def test_preview_job_preserves_attachment_metadata(monkeypatch):
    main = importlib.import_module("main")

    def fake_run_delivery(config, service, *, send_email_fn, recipient_override=None):
        del config, service, recipient_override
        send_email_fn(
            None,
            to_address="preview@example.com",
            subject="Preview Digest",
            body="Preview body",
            html_body="<p>Preview body</p>",
            attachments=[
                {
                    "filename": "ai-signal-daily-2026-04-05.pdf",
                    "mime_type": "application/pdf",
                    "content_bytes": b"%PDF-test",
                }
            ],
            message_id_header="<preview@newsletter-curator.local>",
        )
        return {"status": "completed"}

    monkeypatch.setattr(main, "_run_delivery", fake_run_delivery)

    result = main.preview_job({})

    assert result["status"] == "completed"
    assert result["preview"]["attachments"] == [
        {
            "filename": "ai-signal-daily-2026-04-05.pdf",
            "mime_type": "application/pdf",
            "content_bytes": b"%PDF-test",
        }
    ]
    assert result["preview"]["message_id_header"] == "<preview@newsletter-curator.local>"
