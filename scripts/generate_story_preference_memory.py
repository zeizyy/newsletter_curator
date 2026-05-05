from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as app_main
from curator.jobs import get_repository_from_config
from curator.preference_memory import generate_subscriber_story_preference_memory


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


def debug(message: str, **payload: object) -> None:
    rendered_payload = " ".join(f"{key}={value}" for key, value in payload.items())
    suffix = f" {rendered_payload}" if rendered_payload else ""
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    print(
        f"[story-preference-memory] {timestamp} {message}{suffix}",
        file=sys.stderr,
        flush=True,
    )


def main() -> None:
    args = parse_args()
    debug(
        "starting",
        subscriber_id=args.subscriber_id if args.subscriber_id is not None else "all",
        email=str(args.email or "").strip() or "-",
        limit=args.limit if args.limit is not None else "-",
        click_limit=args.click_limit,
    )
    config = app_main.load_config()
    debug("loaded config")
    repository = get_repository_from_config(config)
    debug("opened repository")
    subscriber_id = args.subscriber_id
    email_address = str(args.email or "").strip().lower()
    if email_address:
        debug("resolving subscriber email", email=email_address)
        subscriber = repository.get_subscriber_by_email(email_address)
        if subscriber is None:
            raise SystemExit(f"No subscriber found for email: {email_address}")
        subscriber_id = int(subscriber["id"])
        debug("resolved subscriber email", email=email_address, subscriber_id=subscriber_id)
    model = str(
        config.get("openai", {}).get("reasoning_model")
        or config.get("openai", {}).get("summary_model")
        or "gpt-5-mini"
    ).strip()
    debug("selected model", model=model)

    if subscriber_id is not None:
        targets = [{"subscriber_id": int(subscriber_id), "email_address": email_address}]
    else:
        targets = repository.list_subscribers_with_new_clicks_for_memory(limit=args.limit)
    debug("resolved targets", target_count=len(targets))

    results = []
    for index, target in enumerate(targets, start=1):
        target_subscriber_id = int(target["subscriber_id"])
        debug(
            "generating subscriber memory",
            index=index,
            target_count=len(targets),
            subscriber_id=target_subscriber_id,
            email=str(target.get("email_address") or "-"),
        )
        result = generate_subscriber_story_preference_memory(
            repository,
            target_subscriber_id,
            model=model,
            click_limit=args.click_limit,
        )
        debug(
            "finished subscriber memory",
            index=index,
            target_count=len(targets),
            subscriber_id=target_subscriber_id,
            status=str(result.get("status") or "unknown"),
            reason=str(result.get("reason") or "-"),
        )
        results.append(result)

    result = {
        "status": "completed",
        "target_count": len(targets),
        "generated_count": sum(1 for item in results if item.get("status") == "generated"),
        "skipped_count": sum(1 for item in results if item.get("status") == "skipped"),
        "results": results,
    }
    debug(
        "completed",
        target_count=result["target_count"],
        generated_count=result["generated_count"],
        skipped_count=result["skipped_count"],
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
