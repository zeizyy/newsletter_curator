from __future__ import annotations

import argparse
import json

import main as delivery_main
from curator.jobs import get_repository_from_config, run_daily_orchestrator_job


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full daily pipeline, optionally overriding recipients for a dry run."
    )
    parser.add_argument(
        "--dry-run-recipient",
        default="",
        help="Send only to this recipient instead of Buttondown or config recipients.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = delivery_main.load_config()
    repository = get_repository_from_config(config)
    service = delivery_main.get_gmail_service(config["paths"])
    dry_run_recipient = str(args.dry_run_recipient or "").strip() or None
    result = run_daily_orchestrator_job(
        config,
        service,
        repository=repository,
        delivery_runner_fn=lambda cfg, svc: delivery_main.run_job(
            cfg,
            svc,
            recipient_override=dry_run_recipient,
        ),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if str(result.get("status", "")).strip() != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
