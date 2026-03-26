from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from curator.jobs import get_repository_from_config
from tests.fakes import FakeGmailService
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

    def fail_buttondown_get(url: str, *, headers: dict, params, timeout: int):
        raise AssertionError("Buttondown recipients should not be fetched during a dry run override")

    monkeypatch.setattr(jobs.requests, "get", fail_buttondown_get)
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
    assert [message["to"] for message in sent_messages] == ["dry-run@example.com"]
