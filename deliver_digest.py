from __future__ import annotations

import argparse
import json
import traceback

import main as delivery_main


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deliver the current digest, optionally overriding recipients for a dry run."
    )
    parser.add_argument(
        "--dry-run-recipient",
        default="",
        help="Send only to this recipient instead of Buttondown or config recipients.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = delivery_main.load_config()
    service = None
    try:
        service = delivery_main.get_gmail_service(config["paths"])
        dry_run_recipient = str(args.dry_run_recipient or "").strip() or None
        result = delivery_main.run_job(config, service, recipient_override=dry_run_recipient)
        try:
            delivery_main.send_delivery_failure_alert_if_needed(
                config,
                service,
                source="deliver_digest.py",
                result=result,
            )
        except Exception as alert_exc:
            print(f"Failed to send alert email: {alert_exc}")
        print(json.dumps(result, indent=2, sort_keys=True))
    except Exception as exc:
        error_details = traceback.format_exc()
        print(error_details)
        try:
            delivery_main.send_delivery_failure_alert_if_needed(
                config,
                service,
                source="deliver_digest.py",
                exception=exc,
                traceback_text=error_details,
            )
        except Exception as alert_exc:
            print(f"Failed to send alert email: {alert_exc}")
        raise


if __name__ == "__main__":
    main()
