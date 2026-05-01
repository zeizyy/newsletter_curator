from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as app_main
from curator.jobs import get_repository_from_config
from curator.preference_memory import generate_story_preference_memories


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate per-subscriber story preference memories from clicked stories."
    )
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        "--subscriber-id",
        type=int,
        default=None,
        help="Generate memory for one subscriber id. By default, all subscribers with new clicks are processed.",
    )
    target_group.add_argument(
        "--email",
        default="",
        help="Generate memory for one subscriber email address.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of subscribers to process when no specific user is provided.",
    )
    parser.add_argument(
        "--click-limit",
        type=int,
        default=50,
        help="Maximum number of recent clicked stories to include per subscriber.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = app_main.load_config()
    repository = get_repository_from_config(config)
    subscriber_id = args.subscriber_id
    email_address = str(args.email or "").strip().lower()
    if email_address:
        subscriber = repository.get_subscriber_by_email(email_address)
        if subscriber is None:
            raise SystemExit(f"No subscriber found for email: {email_address}")
        subscriber_id = int(subscriber["id"])
    model = str(
        config.get("openai", {}).get("reasoning_model")
        or config.get("openai", {}).get("summary_model")
        or "gpt-5-mini"
    ).strip()
    result = generate_story_preference_memories(
        repository,
        model=model,
        subscriber_id=subscriber_id,
        limit=args.limit,
        click_limit=args.click_limit,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
