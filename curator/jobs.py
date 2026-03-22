from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock

from openai import OpenAI

from .config import BASE_DIR
from .content import detect_paywalled_article, extract_links_from_html, fetch_article_text
from .dev import fake_summarize_article
from .gmail import (
    collect_live_gmail_links,
    collect_repository_gmail_links,
    gmail_query_cutoff,
    send_email,
)
from .llm import extract_summary_json, select_top_stories, summarize_article_with_llm
from .pipeline import process_story, run_job as run_pipeline_job
from .rendering import group_summaries_by_category, render_digest_html
from .repository import SQLiteRepository
from .sources import (
    collect_additional_source_links,
    collect_repository_source_links,
    load_canned_source_links,
)


def get_repository_from_config(config: dict) -> SQLiteRepository:
    database_cfg = config.get("database", {})
    database_path = database_cfg.get("path", "data/newsletter_curator.sqlite3")
    if not Path(database_path).is_absolute():
        database_path = Path(BASE_DIR) / database_path
    repository = SQLiteRepository(Path(database_path))
    repository.initialize()
    return repository


def summarize_for_ingest(
    config: dict,
    article_text: str,
    usage_by_model: dict,
    lock: Lock,
) -> tuple[str, str, str]:
    persona_text = str(config.get("persona", {}).get("text", "")).strip()
    development_cfg = config.get("development", {})
    summary_model = config["openai"]["summary_model"]
    if development_cfg.get("fake_inference", False):
        summary_raw = fake_summarize_article(
            article_text,
            usage_by_model,
            lock,
            summary_model,
            persona_text=persona_text,
        )
    else:
        summary_raw = summarize_article_with_llm(
            article_text,
            usage_by_model,
            lock,
            summary_model,
            persona_text=persona_text,
            client_factory=OpenAI,
        )
    headline, body = extract_summary_json(summary_raw)
    return summary_raw, headline, body


def _prepare_ingest_snapshot_candidates(
    stories: list[dict],
    *,
    config: dict,
    repository: SQLiteRepository,
    run_id: int,
    article_fetcher,
    stats: dict,
    failures: list[dict],
) -> list[dict]:
    prepared: list[dict] = []
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

        paywall_detected, paywall_reason = detect_paywalled_article(
            article_text, story.get("url", "")
        )
        prepared.append(
            {
                "story": story,
                "story_id": story_id,
                "article_text": article_text,
                "paywall_detected": paywall_detected,
                "paywall_reason": paywall_reason,
                "summary_raw": "",
                "summary_headline": "",
                "summary_body": "",
            }
        )
    return prepared


def _run_parallel_ingest_summaries(
    prepared: list[dict],
    *,
    config: dict,
    usage_by_model: dict,
    lock: Lock,
) -> int:
    summarizable = [item for item in prepared if not item["paywall_detected"]]
    configured_workers = max(1, int(config.get("limits", {}).get("max_summary_workers", 1) or 1))
    worker_count = min(configured_workers, len(summarizable)) if summarizable else 0
    if worker_count == 0:
        return 0

    def summarize(item: dict) -> tuple[str, str, str]:
        return summarize_for_ingest(
            config,
            item["article_text"],
            usage_by_model,
            lock,
        )

    if worker_count == 1:
        results = [summarize(item) for item in summarizable]
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(summarize, summarizable))

    for item, (summary_raw, summary_headline, summary_body) in zip(summarizable, results, strict=True):
        item["summary_raw"] = summary_raw
        item["summary_headline"] = summary_headline
        item["summary_body"] = summary_body
    return worker_count


def _persist_ingest_snapshots(
    prepared: list[dict],
    *,
    config: dict,
    repository: SQLiteRepository,
    job_name: str,
    stats: dict,
    failures: list[dict],
) -> None:
    for item in prepared:
        story = item["story"]
        paywall_detected = item["paywall_detected"]
        summary_body = str(item["summary_body"]).strip()
        if not paywall_detected and (not summary_body or summary_body == "No article text available."):
            stats["summary_failures"] += 1
            failures.append(
                {
                    "url": story.get("url", ""),
                    "source_name": story.get("source_name", ""),
                    "reason": "empty_summary",
                }
            )
            continue

        repository.upsert_article_snapshot(
            item["story_id"],
            item["article_text"],
            metadata={"job": job_name},
            paywall_detected=paywall_detected,
            paywall_reason=item["paywall_reason"],
            summary_raw=item["summary_raw"],
            summary_headline=item["summary_headline"],
            summary_body=item["summary_body"],
            summary_model=config["openai"]["summary_model"] if not paywall_detected else "",
            summarized_at=datetime.now(UTC).isoformat() if not paywall_detected else None,
        )
        if paywall_detected:
            stats["paywall_stories"] += 1
        stats["snapshots_persisted"] += 1


def run_repository_ttl_cleanup(
    config: dict,
    repository: SQLiteRepository,
    *,
    source_types: list[str] | None = None,
) -> dict[str, int]:
    ttl_days = int(config.get("database", {}).get("ttl_days", 7))
    cutoff = (datetime.now(UTC) - timedelta(days=ttl_days)).isoformat()
    cleanup_result = repository.delete_stories_older_than(
        cutoff,
        source_types=source_types or ["gmail", "additional_source"],
    )
    return {"ttl_days": ttl_days, "cutoff": cutoff, **cleanup_result}


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
    cleanup_result = run_repository_ttl_cleanup(config, repository)
    run_id = repository.create_ingestion_run("additional_source", metadata={"job": "fetch_sources"})
    stats = {
        "run_id": run_id,
        "ttl_cleanup": cleanup_result,
        "stories_seen": 0,
        "stories_persisted": 0,
        "snapshots_persisted": 0,
        "article_failures": 0,
        "paywall_stories": 0,
        "summary_failures": 0,
        "summary_workers": 0,
    }
    failures: list[dict] = []
    usage_by_model: dict = {}
    lock = Lock()

    try:
        stories = source_fetcher(config)
        stats["stories_seen"] = len(stories)
        prepared = _prepare_ingest_snapshot_candidates(
            stories,
            config=config,
            repository=repository,
            run_id=run_id,
            article_fetcher=article_fetcher,
            stats=stats,
            failures=failures,
        )
        stats["summary_workers"] = _run_parallel_ingest_summaries(
            prepared,
            config=config,
            usage_by_model=usage_by_model,
            lock=lock,
        )
        _persist_ingest_snapshots(
            prepared,
            config=config,
            repository=repository,
            job_name="fetch_sources",
            stats=stats,
            failures=failures,
        )

        final_status = "completed"
        return_payload = {
            **stats,
            "status": final_status,
            "failures": failures,
            "usage_by_model": usage_by_model,
        }
    except Exception as exc:
        failures.append({"reason": str(exc)})
        final_status = "failed"
        return_payload = {
            **stats,
            "status": final_status,
            "failures": failures,
            "usage_by_model": usage_by_model,
        }
        raise
    finally:
        repository.complete_ingestion_run(
            run_id,
            status=final_status,
            metadata={
                "job": "fetch_sources",
                "ttl_cleanup": cleanup_result,
                "stories_seen": stats["stories_seen"],
                "stories_persisted": stats["stories_persisted"],
                "snapshots_persisted": stats["snapshots_persisted"],
                "article_failures": stats["article_failures"],
                "paywall_stories": stats["paywall_stories"],
                "summary_failures": stats["summary_failures"],
                "summary_workers": stats["summary_workers"],
                "usage_by_model": usage_by_model,
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
    cleanup_result = run_repository_ttl_cleanup(config, repository)
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
        "ttl_cleanup": cleanup_result,
        "stories_seen": 0,
        "stories_persisted": 0,
        "snapshots_persisted": 0,
        "article_failures": 0,
        "paywall_stories": 0,
        "summary_failures": 0,
        "summary_workers": 0,
    }
    failures: list[dict] = []
    usage_by_model: dict = {}
    lock = Lock()

    try:
        stories = collect_gmail_links_fn(service, config)
        stats["stories_seen"] = len(stories)
        prepared = _prepare_ingest_snapshot_candidates(
            stories,
            config=config,
            repository=repository,
            run_id=run_id,
            article_fetcher=article_fetcher,
            stats=stats,
            failures=failures,
        )
        stats["summary_workers"] = _run_parallel_ingest_summaries(
            prepared,
            config=config,
            usage_by_model=usage_by_model,
            lock=lock,
        )
        _persist_ingest_snapshots(
            prepared,
            config=config,
            repository=repository,
            job_name="fetch_gmail",
            stats=stats,
            failures=failures,
        )

        final_status = "completed"
        return_payload = {
            **stats,
            "status": final_status,
            "failures": failures,
            "usage_by_model": usage_by_model,
        }
    except Exception as exc:
        failures.append({"reason": str(exc)})
        final_status = "failed"
        return_payload = {
            **stats,
            "status": final_status,
            "failures": failures,
            "usage_by_model": usage_by_model,
        }
        raise
    finally:
        repository.complete_ingestion_run(
            run_id,
            status=final_status,
            metadata={
                "job": "fetch_gmail",
                "ttl_cleanup": cleanup_result,
                "stories_seen": stats["stories_seen"],
                "stories_persisted": stats["stories_persisted"],
                "snapshots_persisted": stats["snapshots_persisted"],
                "article_failures": stats["article_failures"],
                "paywall_stories": stats["paywall_stories"],
                "summary_failures": stats["summary_failures"],
                "summary_workers": stats["summary_workers"],
                "usage_by_model": usage_by_model,
                "failures": failures,
            },
        )

    return return_payload


def _required_delivery_source_types(config: dict) -> list[str]:
    source_types: list[str] = []
    quotas = config.get("limits", {}).get("source_quotas", {})
    if int(quotas.get("gmail", 0) or 0) > 0:
        source_types.append("gmail")
    if config.get("additional_sources", {}).get("enabled", False) and int(
        quotas.get("additional_source", 0) or 0
    ) > 0:
        source_types.append("additional_source")
    return source_types


def _delivery_cutoff(config: dict, source_type: str) -> str | None:
    if source_type == "gmail":
        return gmail_query_cutoff(config["gmail"]["query_time_window"])
    if source_type == "additional_source":
        hours = int(config.get("additional_sources", {}).get("hours", 24))
        return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    return None


def assess_delivery_readiness(config: dict, repository: SQLiteRepository) -> dict:
    sources = []
    ready_source_types: list[str] = []
    required_source_types = _required_delivery_source_types(config)

    for source_type in required_source_types:
        cutoff = _delivery_cutoff(config, source_type)
        stories = repository.list_stories(
            source_type=source_type,
            published_after=cutoff,
            include_paywalled=False,
        )
        latest_run = repository.get_latest_ingestion_run(source_type)
        latest_completed_run = repository.get_latest_ingestion_run(source_type, status="completed")
        warnings: list[str] = []
        if latest_run is None:
            warnings.append("no_ingest_run")
        elif latest_run["status"] != "completed":
            warnings.append(f"latest_run_status={latest_run['status']}")
        if latest_completed_run is None:
            warnings.append("no_successful_ingest")
        if not stories:
            warnings.append("no_fresh_stories")
        ready = bool(stories) and latest_completed_run is not None
        if ready:
            ready_source_types.append(source_type)
        sources.append(
            {
                "source_type": source_type,
                "cutoff": cutoff,
                "fresh_story_count": len(stories),
                "ready": ready,
                "latest_run_id": latest_run["id"] if latest_run else None,
                "latest_run_status": latest_run["status"] if latest_run else None,
                "latest_completed_run_id": (
                    latest_completed_run["id"] if latest_completed_run else None
                ),
                "latest_completed_finished_at": (
                    latest_completed_run["finished_at"] if latest_completed_run else None
                ),
                "warnings": warnings,
            }
        )

    return {
        "required_source_types": required_source_types,
        "ready_source_types": ready_source_types,
        "sources": sources,
        "ok": bool(ready_source_types) or not required_source_types,
    }


def run_delivery_job(
    config: dict,
    service,
    *,
    repository: SQLiteRepository | None = None,
    collect_gmail_links_fn=None,
    collect_source_links_fn=None,
    select_top_stories_fn=select_top_stories,
    process_story_fn=None,
    group_summaries_by_category_fn=group_summaries_by_category,
    render_digest_html_fn=render_digest_html,
    send_email_fn=send_email,
) -> dict:
    repository = repository or get_repository_from_config(config)
    readiness = assess_delivery_readiness(config, repository)
    print(
        json.dumps(
            {"event": "delivery_readiness", "readiness": readiness},
            sort_keys=True,
        )
    )
    if not readiness["ok"]:
        raise RuntimeError(
            "No delivery-ready repository data is available for the required source types."
        )

    collect_gmail_links_fn = collect_gmail_links_fn or (
        lambda cfg, svc: collect_repository_gmail_links(cfg, repository=repository)
    )
    collect_source_links_fn = collect_source_links_fn or (
        lambda cfg: collect_repository_source_links(cfg, repository=repository)
    )
    process_story_fn = process_story_fn or (
        lambda item, usage_by_model, lock, max_article_chars, summary_model: process_story(
            item,
            usage_by_model,
            lock,
            max_article_chars,
            summary_model,
            article_fetcher=lambda url, chars, timeout=25, retries=3: "",
        )
    )

    run_id = repository.create_delivery_run(
        metadata={"job": "deliver_digest", "readiness": readiness}
    )
    try:
        pipeline_result = run_pipeline_job(
            config,
            service,
            collect_gmail_links_fn=collect_gmail_links_fn,
            collect_additional_source_links_fn=collect_source_links_fn,
            select_top_stories_fn=select_top_stories_fn,
            process_story_fn=process_story_fn,
            group_summaries_by_category_fn=group_summaries_by_category_fn,
            render_digest_html_fn=render_digest_html_fn,
            send_email_fn=send_email_fn,
        )
        repository.complete_delivery_run(
            run_id,
            status="completed",
            metadata={
                "job": "deliver_digest",
                "readiness": readiness,
                "pipeline_result": pipeline_result,
            },
        )
        return {"run_id": run_id, "status": "completed", **pipeline_result}
    except Exception as exc:
        repository.complete_delivery_run(
            run_id,
            status="failed",
            metadata={
                "job": "deliver_digest",
                "readiness": readiness,
                "error": str(exc),
            },
        )
        raise
