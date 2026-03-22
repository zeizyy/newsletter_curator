from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock

from openai import OpenAI

from .config import BASE_DIR
from .content import (
    detect_paywalled_article,
    enrich_story_with_article_metadata,
    extract_links_from_html,
    fetch_article_details,
)
from .dev import fake_summarize_article
from .dev import fake_score_story_candidates
from .gmail import (
    collect_live_gmail_links,
    collect_repository_gmail_links,
    gmail_query_cutoff,
    send_email,
)
from .llm import (
    extract_summary_json,
    score_story_candidates,
    select_top_stories,
    summarize_article_with_llm,
)
from .pipeline import process_story, run_job as run_pipeline_job
from .rendering import group_summaries_by_category, render_digest_html
from .repository import SQLiteRepository
from .sources import (
    collect_additional_source_links,
    collect_repository_source_links,
    load_canned_source_links,
)
from .telemetry import (
    build_click_url,
    build_open_pixel_url,
    resolve_tracking_base_url,
    rewrite_newsletter_html_for_tracking,
)


def current_newsletter_date() -> str:
    return datetime.now(UTC).date().isoformat()


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


def score_for_ingest(
    config: dict,
    prepared: list[dict],
    usage_by_model: dict,
) -> list[dict]:
    candidates = [item for item in prepared if not item["paywall_detected"]]
    if not candidates:
        return []

    max_ingest_summaries = max(
        1,
        int(config.get("limits", {}).get("max_ingest_summaries", 20) or 20),
    )
    persona_text = str(config.get("persona", {}).get("text", "")).strip()
    development_cfg = config.get("development", {})
    scoring_model = config["openai"]["reasoning_model"]
    scoring_items = []
    for position, item in enumerate(candidates):
        story = item["story"]
        scoring_items.append(
            {
                "_candidate_position": position,
                "anchor_text": story.get("anchor_text", ""),
                "subject": story.get("subject", ""),
                "source_name": story.get("source_name", ""),
                "category": story.get("category", ""),
                "context": story.get("context", ""),
                "article_excerpt": item["article_text"][:600],
                "url": story.get("url", ""),
            }
        )

    if development_cfg.get("fake_inference", False):
        ranked = fake_score_story_candidates(
            scoring_items,
            usage_by_model,
            max_ingest_summaries,
            scoring_model,
            persona_text=persona_text,
        )
    else:
        ranked = score_story_candidates(
            scoring_items,
            usage_by_model,
            max_ingest_summaries,
            scoring_model,
            persona_text=persona_text,
            client_factory=OpenAI,
        )

    if not ranked:
        ranked = scoring_items[:max_ingest_summaries]

    for item in prepared:
        item["summary_selected"] = False
        item["ingest_score"] = ""
        item["ingest_rationale"] = ""

    selected_candidates: list[dict] = []
    seen_positions = set()
    for ranked_item in ranked:
        position = ranked_item.get("_candidate_position")
        if not isinstance(position, int) or position in seen_positions:
            continue
        candidate = candidates[position]
        candidate["summary_selected"] = True
        candidate["ingest_score"] = ranked_item.get("score", "")
        candidate["ingest_rationale"] = ranked_item.get("rationale", "")
        selected_candidates.append(candidate)
        seen_positions.add(position)
    return selected_candidates


def _prepare_ingest_snapshot_candidates(
    stories: list[dict],
    *,
    config: dict,
    article_fetcher,
    stats: dict,
    failures: list[dict],
) -> list[dict]:
    prepared: list[dict] = []
    for story in stories:
        story_record = dict(story)
        article_text = str(story_record.get("article_text", "") or "").strip()
        article_details = {
            "article_text": article_text,
            "document_title": str(story_record.get("anchor_text", "") or "").strip(),
            "document_excerpt": str(story_record.get("context", "") or "").strip(),
        }
        if not article_text:
            fetched = article_fetcher(
                story.get("url", ""),
                config["limits"]["max_article_chars"],
            )
            if isinstance(fetched, dict):
                article_details = {
                    "article_text": str(fetched.get("article_text", "") or "").strip(),
                    "document_title": str(fetched.get("document_title", "") or "").strip(),
                    "document_excerpt": str(fetched.get("document_excerpt", "") or "").strip(),
                }
            else:
                article_details["article_text"] = str(fetched or "").strip()
            article_text = article_details["article_text"]
        if not article_text:
            stats["article_failures"] += 1
            failures.append(
                {
                    "url": story_record.get("url", ""),
                    "source_name": story_record.get("source_name", ""),
                    "reason": "empty_article_text",
                }
            )
            continue

        story_record = enrich_story_with_article_metadata(story_record, article_details)
        paywall_detected, paywall_reason = detect_paywalled_article(
            article_text,
            story_record.get("url", ""),
            document_title=article_details.get("document_title", ""),
            document_excerpt=article_details.get("document_excerpt", ""),
        )
        if paywall_detected:
            stats["paywall_stories"] += 1
        prepared.append(
            {
                "story": story_record,
                "article_text": article_text,
                "paywall_detected": paywall_detected,
                "paywall_reason": paywall_reason,
                "summary_raw": "",
                "summary_headline": "",
                "summary_body": "",
                "summary_selected": False,
                "ingest_score": "",
                "ingest_rationale": "",
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
    summarizable = [
        item for item in prepared if item.get("summary_selected") and not item["paywall_detected"]
    ]
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
    run_id: int,
    job_name: str,
    stats: dict,
    failures: list[dict],
) -> None:
    for item in prepared:
        story = item["story"]
        paywall_detected = item["paywall_detected"]
        summary_selected = bool(item.get("summary_selected"))
        summary_body = str(item["summary_body"]).strip()
        if paywall_detected or not summary_selected:
            continue
        if summary_selected and not paywall_detected and (
            not summary_body or summary_body == "No article text available."
        ):
            stats["summary_failures"] += 1
            failures.append(
                {
                    "url": story.get("url", ""),
                    "source_name": story.get("source_name", ""),
                    "reason": "empty_summary",
                }
            )
            continue

        story_id = repository.upsert_story(story, ingestion_run_id=run_id)
        stats["stories_persisted"] += 1
        repository.upsert_article_snapshot(
            story_id,
            item["article_text"],
            metadata={
                "job": job_name,
                "summary_selected": summary_selected,
                "ingest_score": item.get("ingest_score", ""),
                "ingest_rationale": item.get("ingest_rationale", ""),
            },
            paywall_detected=paywall_detected,
            paywall_reason=item["paywall_reason"],
            summary_raw=item["summary_raw"],
            summary_headline=item["summary_headline"],
            summary_body=item["summary_body"],
            summary_model=(
                config["openai"]["summary_model"]
                if (summary_selected and not paywall_detected)
                else ""
            ),
            summarized_at=(
                datetime.now(UTC).isoformat()
                if (summary_selected and not paywall_detected)
                else None
            ),
        )
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


def run_newsletter_ttl_cleanup(config: dict, repository: SQLiteRepository) -> dict[str, int | str]:
    database_cfg = config.get("database", {})
    ttl_days = int(database_cfg.get("newsletter_ttl_days", database_cfg.get("ttl_days", 7)))
    keep_days = max(ttl_days, 1)
    cutoff_newsletter_date = (
        datetime.now(UTC).date() - timedelta(days=max(keep_days - 1, 0))
    ).isoformat()
    cleanup_result = repository.delete_daily_newsletters_older_than(cutoff_newsletter_date)
    return {
        "ttl_days": keep_days,
        "cutoff_newsletter_date": cutoff_newsletter_date,
        **cleanup_result,
    }


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
    article_fetcher = article_fetcher or fetch_article_details
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
        "scored_candidates": 0,
        "summary_candidates": 0,
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
            article_fetcher=article_fetcher,
            stats=stats,
            failures=failures,
        )
        selected_candidates = score_for_ingest(
            config,
            prepared,
            usage_by_model,
        )
        stats["scored_candidates"] = len([item for item in prepared if not item["paywall_detected"]])
        stats["summary_candidates"] = len(selected_candidates)
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
            run_id=run_id,
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
                "scored_candidates": stats["scored_candidates"],
                "summary_candidates": stats["summary_candidates"],
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
    article_fetcher = article_fetcher or fetch_article_details
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
        "scored_candidates": 0,
        "summary_candidates": 0,
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
            article_fetcher=article_fetcher,
            stats=stats,
            failures=failures,
        )
        selected_candidates = score_for_ingest(
            config,
            prepared,
            usage_by_model,
        )
        stats["scored_candidates"] = len([item for item in prepared if not item["paywall_detected"]])
        stats["summary_candidates"] = len(selected_candidates)
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
            run_id=run_id,
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
                "scored_candidates": stats["scored_candidates"],
                "summary_candidates": stats["summary_candidates"],
                "usage_by_model": usage_by_model,
                "failures": failures,
            },
        )

    return return_payload


def run_daily_orchestrator_job(
    config: dict,
    service,
    *,
    repository: SQLiteRepository | None = None,
    source_fetcher=None,
    article_fetcher=None,
    collect_gmail_links_fn=None,
    delivery_runner_fn=None,
) -> dict:
    repository = repository or get_repository_from_config(config)
    article_fetcher = article_fetcher or fetch_article_details
    delivery_runner_fn = delivery_runner_fn or (
        lambda cfg, svc: run_delivery_job(cfg, svc, repository=repository)
    )

    stages: dict[str, dict] = {}
    stage_order = ["fetch_gmail", "fetch_sources", "deliver_digest"]
    failures: list[dict] = []

    def record_failure(stage_name: str, exc: Exception) -> None:
        stages[stage_name] = {
            "status": "failed",
            "error": str(exc),
        }
        failures.append({"stage": stage_name, "error": str(exc)})

    try:
        stages["fetch_gmail"] = run_fetch_gmail_job(
            config,
            service,
            repository=repository,
            article_fetcher=article_fetcher,
            collect_gmail_links_fn=collect_gmail_links_fn,
        )
    except Exception as exc:
        record_failure("fetch_gmail", exc)

    try:
        stages["fetch_sources"] = run_fetch_sources_job(
            config,
            repository=repository,
            source_fetcher=source_fetcher,
            article_fetcher=article_fetcher,
        )
    except Exception as exc:
        record_failure("fetch_sources", exc)

    try:
        stages["deliver_digest"] = delivery_runner_fn(config, service)
    except Exception as exc:
        record_failure("deliver_digest", exc)

    completed_stages = [
        stage_name
        for stage_name in stage_order
        if stages.get(stage_name, {}).get("status") == "completed"
    ]
    failed_stages = [
        stage_name
        for stage_name in stage_order
        if stages.get(stage_name, {}).get("status") == "failed"
    ]

    if not failed_stages:
        status = "completed"
    elif stages.get("deliver_digest", {}).get("status") == "completed":
        status = "partial_failure"
    else:
        status = "failed"

    result = {
        "status": status,
        "stage_order": stage_order,
        "completed_stages": completed_stages,
        "failed_stages": failed_stages,
        "stages": stages,
        "failures": failures,
    }
    print(json.dumps({"event": "daily_orchestrator", "result": result}, sort_keys=True))
    return result


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
    telemetry_enabled: bool = True,
) -> dict:
    repository = repository or get_repository_from_config(config)
    newsletter_cleanup = run_newsletter_ttl_cleanup(config, repository)
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
    newsletter_date = current_newsletter_date()

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

    def build_tracked_send_html(
        daily_newsletter_id: int,
        *,
        html_body: str,
        selected_items: list[dict],
    ) -> str:
        if not telemetry_enabled:
            return html_body

        base_url = resolve_tracking_base_url(config)
        open_token = repository.ensure_newsletter_open_token(daily_newsletter_id)
        tracked_links = repository.ensure_tracked_links(daily_newsletter_id, selected_items)
        tracked_link_rows = [
            {
                **row,
                "tracked_url": build_click_url(base_url, str(row["click_token"])),
            }
            for row in tracked_links
        ]
        return rewrite_newsletter_html_for_tracking(
            html_body,
            tracked_links=tracked_link_rows,
            open_pixel_url=build_open_pixel_url(base_url, open_token),
        )

    def send_digest(
        *,
        subject: str,
        body: str,
        html_body: str,
        selected_items: list[dict],
        daily_newsletter_id: int | None,
    ) -> int:
        send_html = (
            build_tracked_send_html(
                daily_newsletter_id,
                html_body=html_body,
                selected_items=selected_items,
            )
            if daily_newsletter_id is not None
            else html_body
        )
        sent_count = 0
        for recipient in config["email"]["digest_recipients"]:
            send_email_fn(
                service,
                to_address=recipient,
                subject=subject,
                body=body,
                html_body=send_html,
            )
            sent_count += 1
        return sent_count

    run_id = repository.create_delivery_run(
        metadata={
            "job": "deliver_digest",
            "readiness": readiness,
            "newsletter_ttl_cleanup": newsletter_cleanup,
            "newsletter_date": newsletter_date,
        }
    )
    try:
        cached_newsletter = repository.get_daily_newsletter(newsletter_date)
        if cached_newsletter is not None:
            sent_recipients = send_digest(
                subject=cached_newsletter["subject"],
                body=cached_newsletter["body"],
                html_body=cached_newsletter["html_body"],
                selected_items=cached_newsletter.get("selected_items", []),
                daily_newsletter_id=int(cached_newsletter["id"]),
            )
            cached_result = {
                "status": "completed",
                "cached_newsletter": True,
                "newsletter_date": newsletter_date,
                "ranked_candidates": int(
                    cached_newsletter["metadata"].get("ranked_candidates", 0) or 0
                ),
                "selected": int(cached_newsletter["metadata"].get("selected", 0) or 0),
                "accepted_items": len(cached_newsletter.get("selected_items", [])),
                "accepted_story_items": cached_newsletter.get("selected_items", []),
                "backfilled_count": int(
                    cached_newsletter["metadata"].get("backfilled_count", 0) or 0
                ),
                "skipped_count": int(
                    cached_newsletter["metadata"].get("skipped_count", 0) or 0
                ),
                "sent_recipients": sent_recipients,
                "digest_subject": cached_newsletter["subject"],
                "digest_body": cached_newsletter["body"],
                "digest_html": cached_newsletter["html_body"],
            }
            repository.complete_delivery_run(
                run_id,
                status="completed",
                metadata={
                    "job": "deliver_digest",
                    "readiness": readiness,
                    "newsletter_ttl_cleanup": newsletter_cleanup,
                    "newsletter_date": newsletter_date,
                    "cached_newsletter": True,
                    "daily_newsletter_id": cached_newsletter["id"],
                    "pipeline_result": cached_result,
                },
            )
            return {"run_id": run_id, **cached_result}

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
        daily_newsletter_id = None
        if (
            pipeline_result.get("status") == "completed"
            and str(pipeline_result.get("digest_body", "")).strip()
            and str(pipeline_result.get("digest_html", "")).strip()
        ):
            daily_newsletter_id = repository.upsert_daily_newsletter(
                newsletter_date=newsletter_date,
                delivery_run_id=run_id,
                subject=str(pipeline_result.get("digest_subject", "")).strip(),
                body=str(pipeline_result.get("digest_body", "")).strip(),
                html_body=str(pipeline_result.get("digest_html", "")).strip(),
                selected_items=list(pipeline_result.get("accepted_story_items", [])),
                metadata={
                    "ranked_candidates": pipeline_result.get("ranked_candidates", 0),
                    "selected": pipeline_result.get("selected", 0),
                    "accepted_items": pipeline_result.get("accepted_items", 0),
                    "backfilled_count": pipeline_result.get("backfilled_count", 0),
                    "skipped_count": pipeline_result.get("skipped_count", 0),
                    "newsletter_ttl_cleanup": newsletter_cleanup,
                },
            )
            pipeline_result["sent_recipients"] = send_digest(
                subject=str(pipeline_result.get("digest_subject", "")).strip(),
                body=str(pipeline_result.get("digest_body", "")).strip(),
                html_body=str(pipeline_result.get("digest_html", "")).strip(),
                selected_items=list(pipeline_result.get("accepted_story_items", [])),
                daily_newsletter_id=daily_newsletter_id,
            )
        repository.complete_delivery_run(
            run_id,
            status="completed",
            metadata={
                "job": "deliver_digest",
                "readiness": readiness,
                "newsletter_ttl_cleanup": newsletter_cleanup,
                "newsletter_date": newsletter_date,
                "cached_newsletter": False,
                "daily_newsletter_id": daily_newsletter_id,
                "pipeline_result": pipeline_result,
            },
        )
        return {
            "run_id": run_id,
            "newsletter_date": newsletter_date,
            "cached_newsletter": False,
            "status": "completed",
            **pipeline_result,
        }
    except Exception as exc:
        repository.complete_delivery_run(
            run_id,
            status="failed",
            metadata={
                "job": "deliver_digest",
                "readiness": readiness,
                "newsletter_ttl_cleanup": newsletter_cleanup,
                "newsletter_date": newsletter_date,
                "error": str(exc),
            },
        )
        raise
