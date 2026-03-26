from __future__ import annotations

import argparse
import json

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
    service = delivery_main.get_gmail_service(config["paths"])
    dry_run_recipient = str(args.dry_run_recipient or "").strip() or None
    result = delivery_main.run_job(config, service, recipient_override=dry_run_recipient)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
