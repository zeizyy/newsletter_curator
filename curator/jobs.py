from __future__ import annotations

from pathlib import Path

from .config import BASE_DIR
from .content import extract_links_from_html, fetch_article_text
from .gmail import collect_live_gmail_links
from .repository import SQLiteRepository
from .sources import collect_additional_source_links, load_canned_source_links


def get_repository_from_config(config: dict) -> SQLiteRepository:
    database_cfg = config.get("database", {})
    database_path = database_cfg.get("path", "data/newsletter_curator.sqlite3")
    if not Path(database_path).is_absolute():
        database_path = Path(BASE_DIR) / database_path
    repository = SQLiteRepository(Path(database_path))
    repository.initialize()
    return repository


def run_fetch_sources_job(
    config: dict,
    *,
    repository: SQLiteRepository | None = None,
    source_fetcher=None,
    article_fetcher=None,
) -> dict:
    repository = repository or get_repository_from_config(config)
    if source_fetcher is None:
        if config.get("development", {}).get("use_canned_sources", False):
            source_fetcher = load_canned_source_links
        else:
            source_fetcher = collect_additional_source_links
    article_fetcher = article_fetcher or fetch_article_text
    run_id = repository.create_ingestion_run("additional_source", metadata={"job": "fetch_sources"})
    stats = {
        "run_id": run_id,
        "stories_seen": 0,
        "stories_persisted": 0,
        "snapshots_persisted": 0,
        "article_failures": 0,
    }
    failures: list[dict] = []

    try:
        stories = source_fetcher(config)
        stats["stories_seen"] = len(stories)
        for story in stories:
            story_id = repository.upsert_story(story, ingestion_run_id=run_id)
            stats["stories_persisted"] += 1

            article_text = str(story.get("article_text", "") or "").strip()
            if not article_text:
                article_text = article_fetcher(
                    story.get("url", ""),
                    config["limits"]["max_article_chars"],
                )
            if not article_text:
                stats["article_failures"] += 1
                failures.append(
                    {
                        "url": story.get("url", ""),
                        "source_name": story.get("source_name", ""),
                        "reason": "empty_article_text",
                    }
                )
                continue

            repository.upsert_article_snapshot(
                story_id,
                article_text,
                metadata={"job": "fetch_sources"},
            )
            stats["snapshots_persisted"] += 1

        final_status = "completed"
        return_payload = {**stats, "status": final_status, "failures": failures}
    except Exception as exc:
        failures.append({"reason": str(exc)})
        final_status = "failed"
        return_payload = {**stats, "status": final_status, "failures": failures}
        raise
    finally:
        repository.complete_ingestion_run(
            run_id,
            status=final_status,
            metadata={
                "job": "fetch_sources",
                "stories_seen": stats["stories_seen"],
                "stories_persisted": stats["stories_persisted"],
                "snapshots_persisted": stats["snapshots_persisted"],
                "article_failures": stats["article_failures"],
                "failures": failures,
            },
        )

    return return_payload


def run_fetch_gmail_job(
    config: dict,
    service,
    *,
    repository: SQLiteRepository | None = None,
    article_fetcher=None,
    collect_gmail_links_fn=None,
) -> dict:
    repository = repository or get_repository_from_config(config)
    article_fetcher = article_fetcher or fetch_article_text
    collect_gmail_links_fn = collect_gmail_links_fn or (
        lambda service, config: collect_live_gmail_links(
            service,
            config,
            extract_links_from_html_fn=extract_links_from_html,
        )
    )
    run_id = repository.create_ingestion_run("gmail", metadata={"job": "fetch_gmail"})
    stats = {
        "run_id": run_id,
        "stories_seen": 0,
        "stories_persisted": 0,
        "snapshots_persisted": 0,
        "article_failures": 0,
    }
    failures: list[dict] = []

    try:
        stories = collect_gmail_links_fn(service, config)
        stats["stories_seen"] = len(stories)
        for story in stories:
            story_id = repository.upsert_story(story, ingestion_run_id=run_id)
            stats["stories_persisted"] += 1

            article_text = str(story.get("article_text", "") or "").strip()
            if not article_text:
                article_text = article_fetcher(
                    story.get("url", ""),
                    config["limits"]["max_article_chars"],
                )
            if not article_text:
                stats["article_failures"] += 1
                failures.append(
                    {
                        "url": story.get("url", ""),
                        "source_name": story.get("source_name", ""),
                        "reason": "empty_article_text",
                    }
                )
                continue

            repository.upsert_article_snapshot(
                story_id,
                article_text,
                metadata={"job": "fetch_gmail"},
            )
            stats["snapshots_persisted"] += 1

        final_status = "completed"
        return_payload = {**stats, "status": final_status, "failures": failures}
    except Exception as exc:
        failures.append({"reason": str(exc)})
        final_status = "failed"
        return_payload = {**stats, "status": final_status, "failures": failures}
        raise
    finally:
        repository.complete_ingestion_run(
            run_id,
            status=final_status,
            metadata={
                "job": "fetch_gmail",
                "stories_seen": stats["stories_seen"],
                "stories_persisted": stats["stories_persisted"],
                "snapshots_persisted": stats["snapshots_persisted"],
                "article_failures": stats["article_failures"],
                "failures": failures,
            },
        )

    return return_payload
