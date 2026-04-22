from __future__ import annotations

import argparse
import json

import main as delivery_main
from curator.jobs import get_repository_from_config, run_daily_orchestrator_job


def apply_lookback_days(config: dict, lookback_days: int | None) -> dict:
    if lookback_days is None:
        return config
    if lookback_days < 1:
        raise ValueError("--lookback_days must be at least 1")

    config.setdefault("gmail", {})["query_time_window"] = f"newer_than:{lookback_days}d"
    config.setdefault("additional_sources", {})["hours"] = lookback_days * 24
    config.setdefault("delivery", {})["lookback_days"] = lookback_days
    return config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full daily pipeline, optionally overriding recipients for a dry run."
    )
    parser.add_argument(
        "--dry-run-recipient",
        default="",
        help="Send only to this recipient instead of Buttondown or config recipients.",
    )
    parser.add_argument(
        "--lookback_days",
        "--lookback-days",
        type=int,
        default=None,
        help=(
            "Override the Gmail and additional-source lookback window in days. "
            "Use 7 to manually send the weekly digest regardless of today's schedule."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = delivery_main.load_config()
    lookback_days = args.lookback_days
    config = apply_lookback_days(config, lookback_days)
    repository = get_repository_from_config(config)
    service = delivery_main.get_gmail_service(config["paths"])
    dry_run_recipient = str(args.dry_run_recipient or "").strip() or None
    explicit_lookback = lookback_days is not None
    issue_type_override = None
    if explicit_lookback:
        issue_type_override = "weekly" if lookback_days == 7 else "daily"
    result = run_daily_orchestrator_job(
        config,
        service,
        repository=repository,
        delivery_runner_fn=lambda cfg, svc: delivery_main.run_job(
            cfg,
            svc,
            recipient_override=dry_run_recipient,
            issue_type_override=issue_type_override,
            use_cached_newsletter=not explicit_lookback,
            persist_newsletter=not explicit_lookback,
        ),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if str(result.get("status", "")).strip() != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
