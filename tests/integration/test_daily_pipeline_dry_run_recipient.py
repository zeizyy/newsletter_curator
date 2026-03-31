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
