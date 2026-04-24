from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from curator import config as config_module
from curator.repository import SQLiteRepository


def resolve_database_path(config: dict) -> Path:
    database_path = Path(str(config.get("database", {}).get("path", "data/newsletter_curator.sqlite3")))
    if database_path.is_absolute():
        return database_path
    return config_module.BASE_DIR / database_path


def seed_story(
    repository: SQLiteRepository,
    *,
    run_id: int,
    source_name: str,
    subject: str,
    url: str,
    context: str,
    category: str,
    summary: str,
    article_text: str,
    published_at: str,
) -> int:
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": source_name,
            "subject": subject,
            "url": url,
            "anchor_text": subject,
            "context": context,
            "category": category,
            "published_at": published_at,
            "summary": summary,
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        article_text,
        summary_headline=subject,
        summary_body=summary,
        summarized_at=published_at,
    )
    return story_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed deterministic Daily News Agent stories for local browser testing.",
    )
    parser.add_argument("--config-path", default=config_module.DEFAULT_CONFIG_PATH)
    args = parser.parse_args()

    config = config_module.load_config(args.config_path)
    repository = SQLiteRepository(resolve_database_path(config))
    repository.initialize()

    run_id = repository.create_ingestion_run("additional_source", metadata={"fixture": "daily_news_agent"})
    now = datetime.now(UTC)
    stories = [
        {
            "source_name": "Chip Ledger",
            "subject": "AI chip capex accelerates across hyperscalers",
            "url": "https://example.com/ai/chip-capex-accelerates",
            "context": "Hyperscalers are increasing GPU cluster budgets, rack deployments, and power reservations.",
            "category": "Tech company news & strategy",
            "summary": "Cloud providers are raising AI chip and data center spending, which keeps supply tight and shifts leverage toward infrastructure vendors.",
            "article_text": (
                "Hyperscalers are expanding AI chip budgets faster than prior plans. "
                "The important signal is not only higher GPU purchasing, but also denser racks, power commitments, and longer supplier visibility."
            ),
            "published_at": (now - timedelta(minutes=42)).isoformat(),
        },
        {
            "source_name": "Model Economics",
            "subject": "Inference margins tighten as accelerator demand rises",
            "url": "https://example.com/ai/inference-margins-tighten",
            "context": "AI product teams are balancing model quality, latency, and chip cost inflation.",
            "category": "Markets / stocks / macro / economy",
            "summary": "Accelerator demand is feeding back into inference unit economics, pushing teams to optimize routing, caching, and model size.",
            "article_text": (
                "Inference costs are becoming a product constraint. "
                "Teams are routing simpler prompts to smaller models, caching repeated answers, and watching utilization more closely as accelerator demand climbs."
            ),
            "published_at": (now - timedelta(minutes=28)).isoformat(),
        },
        {
            "source_name": "Search Strategy",
            "subject": "AI answer surfaces pressure publisher click paths",
            "url": "https://example.com/ai/search-answer-surfaces",
            "context": "Search products are resolving more intent inside answer boxes before users click through.",
            "category": "AI policy / society / research",
            "summary": "Answer-first search surfaces compress discovery funnels, making attribution, ranking, and publisher economics more tightly coupled.",
            "article_text": (
                "Answer surfaces are changing the click path. "
                "The product question is whether ranking, citations, and publisher economics can remain aligned when users get more complete answers directly."
            ),
            "published_at": (now - timedelta(minutes=12)).isoformat(),
        },
    ]

    story_ids = [
        seed_story(repository, run_id=run_id, **story)
        for story in stories
    ]
    repository.complete_ingestion_run(run_id, status="completed", metadata={"fixture": "daily_news_agent"})
    print(f"Seeded {len(story_ids)} Daily News Agent fixture stories into {resolve_database_path(config)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
