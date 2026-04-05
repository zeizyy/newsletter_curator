from __future__ import annotations

import importlib


def test_daily_pipeline_passes_dry_run_recipient_to_delivery_runner(monkeypatch):
    daily_pipeline = importlib.import_module("daily_pipeline")

    captured: dict[str, object] = {}

    monkeypatch.setattr(daily_pipeline.delivery_main, "load_config", lambda: {"paths": {}})
    monkeypatch.setattr(daily_pipeline, "get_repository_from_config", lambda config: object())
    monkeypatch.setattr(daily_pipeline.delivery_main, "get_gmail_service", lambda paths: object())

    def fake_run_job(config, service, *, recipient_override=None):
        return {"recipient_override": recipient_override}

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

    assert captured["delivery_result"] == {"recipient_override": "me@example.com"}


def test_daily_pipeline_sends_alert_for_delivery_stage_failure(monkeypatch):
    daily_pipeline = importlib.import_module("daily_pipeline")

    captured: dict[str, object] = {}
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
    monkeypatch.setattr(daily_pipeline.delivery_main, "run_job", lambda config, service, *, recipient_override=None: {})

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

    def fake_send_delivery_failure_alert_if_needed(
        config,
        service,
        *,
        source: str,
        result=None,
        exception=None,
        traceback_text: str = "",
    ):
        captured["config"] = config
        captured["service"] = service
        captured["source"] = source
        captured["result"] = result
        captured["exception"] = exception
        captured["traceback_text"] = traceback_text
        return True

    monkeypatch.setattr(daily_pipeline, "run_daily_orchestrator_job", fake_run_daily_orchestrator_job)
    monkeypatch.setattr(
        daily_pipeline.delivery_main,
        "send_delivery_failure_alert_if_needed",
        fake_send_delivery_failure_alert_if_needed,
    )

    daily_pipeline.main([])

    assert captured["config"] == fake_config
    assert captured["service"] is fake_service
    assert captured["source"] == "daily_pipeline.py"
    assert captured["exception"] is None
    assert captured["traceback_text"] == ""
    assert captured["result"]["stages"]["deliver_digest"]["failed_recipient_count"] == 1
