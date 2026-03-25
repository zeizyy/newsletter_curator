#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

from curator.jobs import BUTTONDOWN_API_VERSION, fetch_buttondown_recipients


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check Buttondown subscriber fetching with the current API key."
    )
    parser.add_argument(
        "--show-emails",
        action="store_true",
        help="Print each resolved recipient email address.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="How many recipient emails to preview when --show-emails is not set.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.getenv("BUTTONDOWN_API_KEY", "").strip()
    if not api_key:
        print("BUTTONDOWN_API_KEY is not set.", file=sys.stderr)
        return 1

    recipients = fetch_buttondown_recipients(api_key=api_key)
    print(f"Buttondown API version: {BUTTONDOWN_API_VERSION}")
    print(f"Resolved recipients: {len(recipients)}")

    if args.show_emails:
        for email_address in recipients:
            print(email_address)
    else:
        preview = recipients[: max(0, args.limit)]
        if preview:
            print(f"Previewing first {len(preview)} recipient(s):")
            for email_address in preview:
                print(email_address)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
