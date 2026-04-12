from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from curator.config import load_config
from curator.jobs import default_preferred_sources, get_repository_from_config, normalize_preferred_sources


def merge_sources(defaults: list[str], existing: list[str]) -> list[str]:
    merged = list(defaults)
    seen = {source.lower() for source in merged}
    for source in normalize_preferred_sources(existing):
        lowered = source.lower()
        if lowered in seen:
            continue
        merged.append(source)
        seen.add(lowered)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill persisted default preferred sources for existing subscribers."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional path to config.yaml. Defaults to NEWSLETTER_CONFIG or config.yaml.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    repository = get_repository_from_config(config)
    available_sources = repository.list_sources_with_selection()
    defaults = default_preferred_sources(available_sources)
    profiles = repository.list_subscriber_delivery_profiles()

    updated = 0
    created = 0
    unchanged = 0

    for profile in profiles:
        subscriber_id = int(profile.get("id") or 0)
        if subscriber_id <= 0:
            continue
        merged_sources = merge_sources(defaults, list(profile.get("preferred_sources") or []))
        current_sources = normalize_preferred_sources(list(profile.get("preferred_sources") or []))
        profile_exists = bool(profile.get("profile_exists"))

        if profile_exists and current_sources == merged_sources:
            unchanged += 1
            continue

        repository.upsert_subscriber_profile(
            subscriber_id,
            persona_text=str(profile.get("persona_text", "") or ""),
            delivery_format=str(profile.get("delivery_format", "email") or "email"),
            preferred_sources=merged_sources,
        )
        if profile_exists:
            updated += 1
        else:
            created += 1

    print(
        json.dumps(
            {
                "status": "completed",
                "default_sources": defaults,
                "subscriber_count": len(profiles),
                "created_profiles": created,
                "updated_profiles": updated,
                "unchanged_profiles": unchanged,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
