from __future__ import annotations

import importlib
from datetime import UTC, datetime

import requests

from curator.jobs import get_repository_from_config
from tests.fakes import FakeGmailService
from tests.helpers import write_temp_config


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 24, 18, 0, 0, tzinfo=tz or UTC)


class FakeButtondownResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self) -> dict:
        return self._payload


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


def test_delivery_uses_buttondown_subscribers_before_yaml(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["fallback@example.com"],
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
        assert headers == {
            "Authorization": "Token test-buttondown-key",
            "X-API-Version": "2025-06-01",
        }
        assert timeout == 15
        if url == "https://api.buttondown.com/v1/subscribers":
            assert params == [
                ("per_page", 100),
                ("-type", "blocked"),
                ("-type", "complained"),
                ("-type", "removed"),
                ("-type", "unactivated"),
                ("-type", "undeliverable"),
                ("-type", "unsubscribed"),
            ]
            return FakeButtondownResponse(
                {
                    "results": [
                        {"email_address": "buttondown-a@example.com"},
                    ],
                    "next": "https://api.buttondown.com/v1/subscribers?page=2",
                }
            )
        assert url == "https://api.buttondown.com/v1/subscribers?page=2"
        assert params is None
        return FakeButtondownResponse(
            {
                "results": [
                    {"email_address": "buttondown-b@example.com"},
                    {"email_address": ""},
                    {"email_address": "buttondown-a@example.com"},
                ],
                "next": None,
            }
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

    result = main.run_job(config, FakeGmailService(messages=[]))

    assert result["status"] == "completed"
    assert result["cached_newsletter"] is True
    assert result["recipient_source"] == "buttondown"
    assert result["sent_recipients"] == 2
    assert len(seen_calls) == 2
    assert [message["to"] for message in sent_messages] == [
        "buttondown-a@example.com",
        "buttondown-b@example.com",
    ]


def test_delivery_falls_back_to_yaml_when_buttondown_fetch_fails(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["fallback@example.com"],
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

    def failing_buttondown_get(url: str, *, headers: dict, params, timeout: int):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(jobs.requests, "get", failing_buttondown_get)

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
    assert result["recipient_source"] == "config_fallback"
    assert result["sent_recipients"] == 1
    assert [message["to"] for message in sent_messages] == ["fallback@example.com"]
