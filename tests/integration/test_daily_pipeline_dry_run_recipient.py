from __future__ import annotations

import importlib

import pytest


def test_daily_pipeline_passes_dry_run_recipient_to_delivery_runner(monkeypatch):
    daily_pipeline = importlib.import_module("daily_pipeline")

    captured: dict[str, object] = {}

    monkeypatch.setattr(daily_pipeline.delivery_main, "load_config", lambda: {"paths": {}})
    monkeypatch.setattr(daily_pipeline, "get_repository_from_config", lambda config: object())
    monkeypatch.setattr(daily_pipeline.delivery_main, "get_gmail_service", lambda paths: object())

    def fake_run_job(config, service, *, recipient_override=None, issue_type_override=None):
        return {
            "recipient_override": recipient_override,
            "issue_type_override": issue_type_override,
        }

    def fake_run_daily_orchestrator_job(
        config,
        service,
        *,
        repository=None,
        source_fetcher=None,
        article_fetcher=None,
        collect_gmail_links_fn=None,
        delivery_runner_fn=None,
    ):
        captured["delivery_result"] = delivery_runner_fn(config, service)
        return {"status": "completed"}

    monkeypatch.setattr(daily_pipeline.delivery_main, "run_job", fake_run_job)
    monkeypatch.setattr(daily_pipeline, "run_daily_orchestrator_job", fake_run_daily_orchestrator_job)

    daily_pipeline.main(["--dry-run-recipient", "me@example.com"])

    assert captured["delivery_result"] == {
        "recipient_override": "me@example.com",
        "issue_type_override": None,
    }


def test_daily_pipeline_passes_weekly_digest_override_to_delivery_runner(monkeypatch):
    daily_pipeline = importlib.import_module("daily_pipeline")

    captured: dict[str, object] = {}

    monkeypatch.setattr(daily_pipeline.delivery_main, "load_config", lambda: {"paths": {}})
    monkeypatch.setattr(daily_pipeline, "get_repository_from_config", lambda config: object())
    monkeypatch.setattr(daily_pipeline.delivery_main, "get_gmail_service", lambda paths: object())

    def fake_run_job(config, service, *, recipient_override=None, issue_type_override=None):
        return {
            "recipient_override": recipient_override,
            "issue_type_override": issue_type_override,
        }

    def fake_run_daily_orchestrator_job(
        config,
        service,
        *,
        repository=None,
        source_fetcher=None,
        article_fetcher=None,
        collect_gmail_links_fn=None,
        delivery_runner_fn=None,
    ):
        captured["delivery_result"] = delivery_runner_fn(config, service)
        return {"status": "completed"}

    monkeypatch.setattr(daily_pipeline.delivery_main, "run_job", fake_run_job)
    monkeypatch.setattr(daily_pipeline, "run_daily_orchestrator_job", fake_run_daily_orchestrator_job)

    daily_pipeline.main(["--weekly-digest", "--dry-run-recipient", "me@example.com"])

    assert captured["delivery_result"] == {
        "recipient_override": "me@example.com",
        "issue_type_override": "weekly",
    }


def test_daily_pipeline_exits_nonzero_for_delivery_stage_failure(monkeypatch):
    daily_pipeline = importlib.import_module("daily_pipeline")

    fake_service = object()
    fake_config = {
        "paths": {},
        "email": {
            "alert_recipient": "admin@example.com",
            "alert_subject_prefix": "[ALERT] Newsletter Curator Failure",
        },
    }

    monkeypatch.setattr(daily_pipeline.delivery_main, "load_config", lambda: fake_config)
    monkeypatch.setattr(daily_pipeline, "get_repository_from_config", lambda config: object())
    monkeypatch.setattr(daily_pipeline.delivery_main, "get_gmail_service", lambda paths: fake_service)
    monkeypatch.setattr(
        daily_pipeline.delivery_main,
        "run_job",
        lambda config, service, *, recipient_override=None, issue_type_override=None: {},
    )

    def fake_run_daily_orchestrator_job(
        config,
        service,
        *,
        repository=None,
        source_fetcher=None,
        article_fetcher=None,
        collect_gmail_links_fn=None,
        delivery_runner_fn=None,
    ):
        return {
            "status": "partial_failure",
            "stages": {
                "deliver_digest": {
                    "status": "partial_failure",
                    "failed_recipient_count": 1,
                    "failed_recipients": [
                        {
                            "recipient": "fail@example.com",
                            "error": "rate limit exceeded",
                            "error_type": "FakeRateLimitError",
                            "error_status_code": 429,
                            "error_code": "",
                            "attempts": 3,
                            "retryable": False,
                            "message_id_header": "<delivery-test@example.com>",
                        }
                    ],
                }
            },
            "completed_stages": ["fetch_gmail", "fetch_sources"],
            "partial_failure_stages": ["deliver_digest"],
            "failed_stages": [],
            "failures": [],
        }

    monkeypatch.setattr(daily_pipeline, "run_daily_orchestrator_job", fake_run_daily_orchestrator_job)

    with pytest.raises(SystemExit) as exc_info:
        daily_pipeline.main([])

    assert exc_info.value.code == 1
