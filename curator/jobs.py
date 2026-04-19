from __future__ import annotations

import hashlib
import inspect
import json
import os
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from openai import OpenAI
import requests

from .config import BASE_DIR, DEFAULT_ENABLED_SOURCE_NAMES, is_default_enabled_source_name
from .content import (
    detect_paywalled_article,
    enrich_story_with_article_metadata,
    extract_links_from_html,
    fetch_article_details,
)
from .dev import fake_summarize_article
from .dev import fake_score_story_candidates
from .gmail import (
    build_delivery_message_id,
    collect_live_gmail_links,
    collect_repository_gmail_links,
    gmail_query_cutoff,
    send_email,
    send_email_with_retry_and_dedupe,
)
from .llm import (
    score_story_candidates,
    select_top_stories,
    summarize_article_with_llm,
)
from .observability import emit_event
from .pdf import render_digest_pdf
from .pipeline import process_story, run_job as run_pipeline_job
from .pricing import estimate_openai_text_cost_usd
from .rendering import (
    group_summaries_by_category,
    render_digest_text,
    render_digest_html,
    render_email_safe_digest_html,
)
from .repository import (
    DEFAULT_AUDIENCE_KEY,
    DEFAULT_SUBSCRIBER_DELIVERY_FORMAT,
    SQLiteRepository,
    normalize_subscriber_delivery_format,
)
from .runtime import finish_runtime_capture, start_runtime_capture
from .sources import (
    collect_additional_source_links,
    collect_repository_source_links,
    load_canned_source_links,
)
from .summary_format import canonicalize_summary_json
from .telemetry import (
    build_settings_url,
    build_click_url,
    build_open_pixel_url,
    resolve_tracking_base_url,
    rewrite_newsletter_html_for_tracking,
)

BUTTONDOWN_SUBSCRIBERS_URL = "https://api.buttondown.com/v1/subscribers"
BUTTONDOWN_API_VERSION = "2025-06-01"
BUTTONDOWN_PAGE_SIZE = 100
BUTTONDOWN_EXCLUDED_SUBSCRIBER_TYPES = (
    "blocked",
    "complained",
    "removed",
    "unactivated",
    "undeliverable",
    "unsubscribed",
)
WEEKLY_DIGEST_LOOKBACK_DAYS = 7
PACIFIC_TIMEZONE = ZoneInfo("America/Los_Angeles")


def current_newsletter_date() -> str:
    return current_delivery_datetime().date().isoformat()


def current_delivery_datetime() -> datetime:
    return datetime.now(UTC).astimezone(PACIFIC_TIMEZONE)


def delivery_issue_type_for_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    weekday = value.astimezone(PACIFIC_TIMEZONE).weekday()
    if weekday <= 4:
        return "daily"
    if weekday == 5:
        return "weekly"
    return "skipped"


def delivery_schedule_ignored() -> bool:
    return str(os.getenv("CURATOR_IGNORE_DELIVERY_SCHEDULE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def normalize_issue_type_override(issue_type_override: str | None) -> str | None:
    normalized = str(issue_type_override or "").strip().lower()
    if not normalized:
        return None
    if normalized not in {"daily", "weekly"}:
        raise ValueError(f"Unsupported delivery issue type override: {issue_type_override}")
    return normalized


def delivery_config_for_issue(config: dict, issue_type: str) -> dict:
    if issue_type != "weekly":
        return config

    weekly_config = deepcopy(config)
    weekly_config.setdefault("gmail", {})["query_time_window"] = (
        f"newer_than:{WEEKLY_DIGEST_LOOKBACK_DAYS}d"
    )
    weekly_config.setdefault("additional_sources", {})["hours"] = WEEKLY_DIGEST_LOOKBACK_DAYS * 24
    weekly_config.setdefault("delivery", {})["issue_type"] = "weekly"
    email_cfg = weekly_config.setdefault("email", {})
    weekly_subject = str(email_cfg.get("weekly_digest_subject", "")).strip()
    if weekly_subject:
        email_cfg["digest_subject"] = weekly_subject
    return weekly_config


def get_repository_from_config(config: dict) -> SQLiteRepository:
    database_cfg = config.get("database", {})
    database_path = database_cfg.get("path", "data/newsletter_curator.sqlite3")
    if not Path(database_path).is_absolute():
        database_path = Path(BASE_DIR) / database_path
    repository = SQLiteRepository(Path(database_path))
    allow_schema_reset = bool(database_cfg.get("allow_schema_reset", False)) or str(
        os.getenv("CURATOR_ALLOW_SCHEMA_RESET", "")
    ).strip().lower() in {"1", "true", "yes", "on"}
    repository.initialize(allow_schema_reset=allow_schema_reset)
    return repository


def normalize_digest_recipients(raw_recipients: list[str] | tuple[str, ...] | None) -> list[str]:
    recipients: list[str] = []
    seen: set[str] = set()
    for raw in raw_recipients or []:
        normalized = str(raw).strip().lower()
        if not normalized or normalized in seen:
            continue
        recipients.append(normalized)
        seen.add(normalized)
    return recipients


def _buttondown_subscriber_email(subscriber: dict) -> str:
    return str(subscriber.get("email_address") or "").strip().lower()


def fetch_buttondown_subscribers(
    *,
    api_key: str,
    requests_get=None,
) -> list[dict]:
    requests_get = requests_get or requests.get
    headers = {
        "Authorization": f"Token {api_key}",
        "X-API-Version": BUTTONDOWN_API_VERSION,
    }
    params: list[tuple[str, str | int]] | None = [("per_page", BUTTONDOWN_PAGE_SIZE)]
    params.extend(("-type", subscriber_type) for subscriber_type in BUTTONDOWN_EXCLUDED_SUBSCRIBER_TYPES)
    subscribers: list[dict] = []
    seen: set[str] = set()
    next_url: str | None = BUTTONDOWN_SUBSCRIBERS_URL
    while next_url:
        response = requests_get(
            next_url,
            headers=headers,
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Buttondown subscribers response did not return a paginated object.")
        results = payload.get("results", [])
        if not isinstance(results, list):
            raise ValueError("Buttondown subscribers response did not contain a list of results.")
        for subscriber in results:
            if not isinstance(subscriber, dict):
                continue
            email_address = _buttondown_subscriber_email(subscriber)
            if not email_address or email_address in seen:
                continue
            subscribers.append({"email": email_address})
            seen.add(email_address)
        next_value = payload.get("next")
        next_url = str(next_value).strip() if next_value else None
        params = None
    return subscribers


def fetch_buttondown_recipients(
    *,
    api_key: str,
    requests_get=None,
) -> list[str]:
    return [
        subscriber["email"]
        for subscriber in fetch_buttondown_subscribers(
            api_key=api_key,
            requests_get=requests_get,
        )
    ]

def _resolve_buttondown_subscribers(
    configured_recipients: list[str],
    *,
    requests_get=None,
) -> tuple[list[dict], str]:
    requests_get = requests_get or requests.get
    buttondown_api_key = os.getenv("BUTTONDOWN_API_KEY", "").strip()
    if not buttondown_api_key:
        return [], "config"
    try:
        buttondown_subscribers = fetch_buttondown_subscribers(
            api_key=buttondown_api_key,
            requests_get=requests_get,
        )
    except (requests.RequestException, ValueError) as exc:
        emit_event(
            "buttondown_subscribers_fallback",
            reason=str(exc),
            fallback_recipient_count=len(configured_recipients),
        )
        return [], "config_fallback"
    if buttondown_subscribers:
        return buttondown_subscribers, "buttondown"
    emit_event(
        "buttondown_subscribers_empty_fallback",
        fallback_recipient_count=len(configured_recipients),
    )
    return [], "config_fallback"

def resolve_digest_recipients(
    config: dict,
    *,
    requests_get=None,
) -> tuple[list[str], str]:
    configured_recipients = normalize_digest_recipients(
        config.get("email", {}).get("digest_recipients", [])
    )
    buttondown_subscribers, recipient_source = _resolve_buttondown_subscribers(
        configured_recipients,
        requests_get=requests_get,
    )
    if buttondown_subscribers:
        return [subscriber["email"] for subscriber in buttondown_subscribers], recipient_source
    return configured_recipients, recipient_source


def normalize_preferred_sources(
    raw_preferred_sources: list[str] | tuple[str, ...] | None,
) -> list[str]:
    preferred_sources: list[str] = []
    seen: set[str] = set()
    for raw in raw_preferred_sources or []:
        source_name = str(raw).strip()
        normalized = source_name.lower()
        if not source_name or normalized in seen:
            continue
        preferred_sources.append(source_name)
        seen.add(normalized)
    return preferred_sources


def default_preferred_sources(available_sources: list[dict] | tuple[dict, ...] | None) -> list[str]:
    defaults: list[str] = []
    seen: set[str] = set()
    for source in available_sources or []:
        source_name = str(source.get("source_name", "")).strip()
        normalized = source_name.lower()
        if (
            not source_name
            or normalized in seen
            or not bool(source.get("enabled", True))
            or not is_default_enabled_source_name(source_name)
        ):
            continue
        defaults.append(source_name)
        seen.add(normalized)
    return defaults


def enabled_additional_source_names(repository: SQLiteRepository) -> list[str]:
    enabled_names = {str(name).strip().lower() for name in DEFAULT_ENABLED_SOURCE_NAMES}
    for source in repository.list_sources_with_selection():
        if str(source.get("source_type", "")).strip() != "additional_source":
            continue
        source_name = str(source.get("source_name", "")).strip()
        normalized = source_name.lower()
        if not source_name:
            continue
        if bool(source.get("enabled", True)):
            enabled_names.add(normalized)
        else:
            enabled_names.discard(normalized)
    return sorted(enabled_names)


def collect_enabled_additional_source_links(config: dict, repository: SQLiteRepository) -> list[dict]:
    try:
        signature = inspect.signature(collect_additional_source_links)
    except (TypeError, ValueError):
        signature = None
    if signature is None or "allowed_source_names" not in signature.parameters:
        return collect_additional_source_links(config)
    return collect_additional_source_links(
        config,
        allowed_source_names=enabled_additional_source_names(repository),
    )


def subscriber_profile_key(
    persona_text: str,
    preferred_sources: list[str],
    delivery_format: str = DEFAULT_SUBSCRIBER_DELIVERY_FORMAT,
) -> str:
    payload = json.dumps(
        {
            "persona_text": str(persona_text).strip(),
            "preferred_sources": [source.lower() for source in preferred_sources],
            "delivery_format": normalize_subscriber_delivery_format(delivery_format),
        },
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]


def subscriber_audience_key(
    persona_text: str,
    preferred_sources: list[str],
) -> str:
    payload = json.dumps(
        {
            "persona_text": str(persona_text).strip(),
            "preferred_sources": [source.lower() for source in preferred_sources],
        },
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]


def finalize_delivery_newsletter(body: str, html_body: str) -> tuple[str, str]:
    return str(body or "").strip(), str(html_body or "").strip()


def resolve_delivery_subscribers(
    config: dict,
    *,
    repository: SQLiteRepository | None = None,
    requests_get=None,
    recipient_override: str | None = None,
) -> tuple[list[dict], str]:
    if str(recipient_override or "").strip():
        recipients = normalize_digest_recipients([recipient_override])
        recipient_source = "dry_run_override"
    else:
        configured_recipients = normalize_digest_recipients(
            config.get("email", {}).get("digest_recipients", [])
        )
        buttondown_subscribers, recipient_source = _resolve_buttondown_subscribers(
            configured_recipients,
            requests_get=requests_get,
        )
        if buttondown_subscribers:
            recipients = [subscriber["email"] for subscriber in buttondown_subscribers]
        else:
            recipients = configured_recipients

    db_profiles_by_email: dict[str, dict] = {}
    available_sources = repository.list_sources_with_selection() if repository is not None else []
    seeded_default_sources = default_preferred_sources(available_sources)
    if repository is not None:
        for email in recipients:
            repository.upsert_subscriber(email)
        db_profiles_by_email = {
            profile["email_address"]: profile
            for profile in repository.list_subscriber_delivery_profiles()
            if str(profile.get("email_address", "")).strip()
        }
        for email in recipients:
            profile = db_profiles_by_email.get(email)
            if profile is not None and bool(profile.get("profile_exists")):
                continue
            if not seeded_default_sources:
                continue
            subscriber = repository.get_subscriber_by_email(email)
            if subscriber is None:
                continue
            repository.upsert_subscriber_profile(
                int(subscriber["id"]),
                preferred_sources=seeded_default_sources,
            )
            seeded_profile = repository.get_subscriber_delivery_profile(email)
            if seeded_profile is not None:
                db_profiles_by_email[email] = seeded_profile

    default_persona_text = str(config.get("persona", {}).get("text", "")).strip()
    subscribers: list[dict] = []
    for email in recipients:
        db_profile = db_profiles_by_email.get(email)
        persona_text = str((db_profile or {}).get("persona_text") or default_persona_text).strip()
        delivery_format = normalize_subscriber_delivery_format((db_profile or {}).get("delivery_format"))
        preferred_sources = normalize_preferred_sources((db_profile or {}).get("preferred_sources", []))
        subscribers.append(
            {
                "email": email,
                "persona_text": persona_text,
                "delivery_format": delivery_format,
                "preferred_sources": preferred_sources,
                "audience_key": subscriber_audience_key(
                    persona_text,
                    preferred_sources,
                ),
                "profile_key": subscriber_profile_key(
                    persona_text,
                    preferred_sources,
                    delivery_format,
                ),
            }
        )
    return subscribers, recipient_source


def group_delivery_subscribers(subscribers: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for subscriber in subscribers:
        profile_key = str(subscriber.get("profile_key", "")).strip()
        if not profile_key:
            continue
        group = grouped.get(profile_key)
        if group is None:
            group = {
                "profile_key": profile_key,
                "audience_key": str(subscriber.get("audience_key", "")).strip(),
                "persona_text": str(subscriber.get("persona_text", "")).strip(),
                "delivery_format": normalize_subscriber_delivery_format(
                    subscriber.get("delivery_format")
                ),
                "preferred_sources": list(subscriber.get("preferred_sources") or []),
                "recipients": [],
            }
            grouped[profile_key] = group
        group["recipients"].append(str(subscriber.get("email", "")).strip().lower())
    return list(grouped.values())


def summarize_for_ingest(
    config: dict,
    article_text: str,
    usage_by_model: dict,
    lock: Lock,
) -> tuple[str, str, str]:
    development_cfg = config.get("development", {})
    summary_model = config["openai"]["summary_model"]
    if development_cfg.get("fake_inference", False):
        summary_raw = fake_summarize_article(
            article_text,
            usage_by_model,
            lock,
            summary_model,
        )
    else:
        summary_raw = summarize_article_with_llm(
            article_text,
            usage_by_model,
            lock,
            summary_model,
            client_factory=OpenAI,
        )
    canonical_summary_raw, normalized = canonicalize_summary_json(summary_raw)
    return (
        canonical_summary_raw,
        str(normalized.get("headline", "")).strip(),
        str(normalized.get("body", "")).strip(),
    )


def _log_ingest_progress(job_name: str, stage: str, **payload) -> None:
    emit_event(
        "ingest_progress",
        job=job_name,
        stage=stage,
        **payload,
    )


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
        int(config.get("limits", {}).get("max_ingest_summaries", 25) or 25),
    )
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
                "article_excerpt": str(item.get("article_excerpt", "") or item.get("article_text", ""))[:600],
                "url": story.get("url", ""),
            }
        )

    if development_cfg.get("fake_inference", False):
        ranked = fake_score_story_candidates(
            scoring_items,
            usage_by_model,
            max_ingest_summaries,
            scoring_model,
        )
    else:
        ranked = score_story_candidates(
            scoring_items,
            usage_by_model,
            max_ingest_summaries,
            scoring_model,
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


def score_gmail_stories_for_fetch(
    config: dict,
    stories: list[dict],
    usage_by_model: dict,
) -> list[dict]:
    if not stories:
        return []

    max_fetch_after_score = max(
        1,
        int(config.get("limits", {}).get("max_gmail_fetch_after_score", 25) or 25),
    )
    development_cfg = config.get("development", {})
    scoring_model = config["openai"]["reasoning_model"]

    scoring_items = []
    for position, story in enumerate(stories):
        scoring_items.append(
            {
                "_candidate_position": position,
                "anchor_text": story.get("anchor_text", ""),
                "subject": story.get("subject", ""),
                "source_name": story.get("source_name", ""),
                "category": story.get("category", ""),
                "context": story.get("context", ""),
                "article_excerpt": "",
                "url": story.get("url", ""),
            }
        )

    if development_cfg.get("fake_inference", False):
        ranked = fake_score_story_candidates(
            scoring_items,
            usage_by_model,
            max_fetch_after_score,
            scoring_model,
        )
    else:
        ranked = score_story_candidates(
            scoring_items,
            usage_by_model,
            max_fetch_after_score,
            scoring_model,
            client_factory=OpenAI,
        )

    if not ranked:
        ranked = scoring_items[:max_fetch_after_score]

    selected: list[dict] = []
    seen_positions = set()
    for ranked_item in ranked:
        position = ranked_item.get("_candidate_position")
        if not isinstance(position, int) or position in seen_positions:
            continue
        selected.append(dict(stories[position]))
        seen_positions.add(position)
        if len(selected) >= max_fetch_after_score:
            break
    return selected


def _prepare_ingest_snapshot_candidates(
    stories: list[dict],
    *,
    config: dict,
    article_fetcher,
    stats: dict,
    failures: list[dict],
    job_name: str,
    repository: SQLiteRepository,
    run_id: int,
) -> list[dict]:
    fetch_timeout = int(config.get("limits", {}).get("article_fetch_timeout", 15) or 15)
    fetch_retries = int(config.get("limits", {}).get("article_fetch_retries", 2) or 2)
    configured_workers = max(1, int(config.get("limits", {}).get("max_fetch_workers", 5) or 5))
    worker_count = min(configured_workers, len(stories)) if stories else 0

    def prepare_one(index: int, story: dict) -> dict:
        story_record = dict(story)
        article_text = str(story_record.get("article_text", "") or "").strip()
        article_details = {
            "article_text": article_text,
            "document_title": str(story_record.get("anchor_text", "") or "").strip(),
            "document_excerpt": str(story_record.get("context", "") or "").strip(),
            "published_at": str(story_record.get("published_at", "") or "").strip(),
        }
        if not article_text:
            _log_ingest_progress(
                job_name,
                "article_fetch_started",
                index=index + 1,
                total=len(stories),
                source_name=story_record.get("source_name", ""),
                subject=story_record.get("subject", ""),
                url=story_record.get("url", ""),
            )
            fetched = article_fetcher(
                story.get("url", ""),
                config["limits"]["max_article_chars"],
                timeout=fetch_timeout,
                retries=fetch_retries,
            )
            if isinstance(fetched, dict):
                article_details = {
                    "article_text": str(fetched.get("article_text", "") or "").strip(),
                    "document_title": str(fetched.get("document_title", "") or "").strip(),
                    "document_excerpt": str(fetched.get("document_excerpt", "") or "").strip(),
                    "published_at": str(fetched.get("published_at", "") or "").strip(),
                    "access_blocked": fetched.get("access_blocked"),
                    "access_reason": str(fetched.get("access_reason", "") or "").strip(),
                    "access_signals": fetched.get("access_signals", {}) or {},
                }
            else:
                article_details["article_text"] = str(fetched or "").strip()
            article_text = article_details["article_text"]
            _log_ingest_progress(
                job_name,
                "article_fetch_finished",
                index=index + 1,
                total=len(stories),
                source_name=story_record.get("source_name", ""),
                subject=story_record.get("subject", ""),
                url=story_record.get("url", ""),
                article_text_chars=len(article_text),
            )
        else:
            _log_ingest_progress(
                job_name,
                "article_fetch_reused",
                index=index + 1,
                total=len(stories),
                source_name=story_record.get("source_name", ""),
                subject=story_record.get("subject", ""),
                url=story_record.get("url", ""),
                article_text_chars=len(article_text),
            )
        if not article_text:
            return {
                "prepared": None,
                "failure": {
                    "url": story_record.get("url", ""),
                    "source_name": story_record.get("source_name", ""),
                    "reason": "empty_article_text",
                },
                "paywall_detected": False,
            }

        story_record = enrich_story_with_article_metadata(story_record, article_details)
        access_signals = article_details.get("access_signals", {}) or {}
        if "access_blocked" in article_details:
            paywall_detected = bool(article_details.get("access_blocked"))
            paywall_reason = str(article_details.get("access_reason", "") or "")
        else:
            paywall_detected, paywall_reason = detect_paywalled_article(
                article_text,
                story_record.get("url", ""),
                document_title=article_details.get("document_title", ""),
                document_excerpt=article_details.get("document_excerpt", ""),
            )
        return {
            "prepared": {
                "story": story_record,
                "article_text": article_text,
                "paywall_detected": paywall_detected,
                "paywall_reason": paywall_reason,
                "access_signals": access_signals,
                "summary_raw": "",
                "summary_headline": "",
                "summary_body": "",
                "summary_selected": False,
                "ingest_score": "",
                "ingest_rationale": "",
            },
            "failure": None,
            "paywall_detected": paywall_detected,
        }

    prepared_by_index: list[dict | None] = [None] * len(stories)
    completed = 0

    def consume_result(index: int, result: dict) -> None:
        nonlocal completed
        completed += 1
        failure = result.get("failure")
        if failure:
            stats["article_failures"] += 1
            failures.append(failure)
        prepared_item = result.get("prepared")
        if prepared_item is not None:
            prepared_by_index[index] = prepared_item
            _checkpoint_ingest_item(
                prepared_item,
                repository=repository,
                run_id=run_id,
                job_name=job_name,
            )
            stats["checkpointed_stories"] += 1
            stats["checkpointed_snapshots"] += 1
            _log_ingest_progress(
                job_name,
                "checkpoint_finished",
                index=index + 1,
                total=len(stories),
                story_id=prepared_item.get("story_id"),
                source_name=prepared_item.get("story", {}).get("source_name", ""),
                subject=prepared_item.get("story", {}).get("subject", ""),
                url=prepared_item.get("story", {}).get("url", ""),
                paywall_detected=result.get("paywall_detected", False),
            )
            if result.get("paywall_detected"):
                stats["paywall_stories"] += 1
        if completed == len(stories) or completed % 5 == 0:
            _log_ingest_progress(
                job_name,
                "article_fetch_progress",
                completed=completed,
                total=len(stories),
                article_failures=stats["article_failures"],
            )

    if worker_count <= 1:
        for index, story in enumerate(stories):
            consume_result(index, prepare_one(index, story))
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(prepare_one, index, story): index
                for index, story in enumerate(stories)
            }
            for future in as_completed(futures):
                consume_result(futures[future], future.result())

    prepared = [item for item in prepared_by_index if item is not None]
    _log_ingest_progress(
        job_name,
        "article_fetch_complete",
        prepared_candidates=len(prepared),
        total=len(stories),
        fetch_workers=worker_count,
        article_failures=stats["article_failures"],
        paywall_stories=stats["paywall_stories"],
    )
    return prepared


def _run_parallel_ingest_summaries(
    prepared: list[dict],
    *,
    config: dict,
    repository: SQLiteRepository,
    usage_by_model: dict,
    lock: Lock,
    job_name: str,
) -> int:
    summarizable = [
        item for item in prepared if item.get("summary_selected") and not item["paywall_detected"]
    ]
    configured_workers = max(1, int(config.get("limits", {}).get("max_summary_workers", 1) or 1))
    worker_count = min(configured_workers, len(summarizable)) if summarizable else 0
    if worker_count == 0:
        return 0

    def summarize(item: dict) -> tuple[str, str, str]:
        _log_ingest_progress(
            job_name,
            "summary_started",
            story_id=item.get("story_id"),
            source_name=item.get("story", {}).get("source_name", ""),
            subject=item.get("story", {}).get("subject", ""),
            url=item.get("story", {}).get("url", ""),
        )
        article_text = str(item.get("article_text", "") or "")
        if not article_text:
            article_text = repository.get_article_text_for_story(int(item["story_id"]))
        summary_raw, summary_headline, summary_body = summarize_for_ingest(
            config,
            article_text,
            usage_by_model,
            lock,
        )
        _log_ingest_progress(
            job_name,
            "summary_finished",
            story_id=item.get("story_id"),
            source_name=item.get("story", {}).get("source_name", ""),
            subject=item.get("story", {}).get("subject", ""),
            url=item.get("story", {}).get("url", ""),
            summary_chars=len(summary_body),
        )
        return summary_raw, summary_headline, summary_body

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


def _checkpoint_ingest_item(
    item: dict,
    *,
    repository: SQLiteRepository,
    run_id: int,
    job_name: str,
) -> None:
    story_id = repository.upsert_story(item["story"], ingestion_run_id=run_id)
    item["story_id"] = story_id
    repository.upsert_article_snapshot(
        story_id,
        item["article_text"],
        metadata={
            "job": job_name,
            "checkpointed": True,
            "summary_selected": False,
            "ingest_score": "",
            "ingest_rationale": "",
            "access_signals": item.get("access_signals", {}),
        },
        paywall_detected=item["paywall_detected"],
        paywall_reason=item["paywall_reason"],
        summary_raw="",
        summary_headline="",
        summary_body="",
        summary_model="",
        summarized_at=None,
    )
    item["article_excerpt"] = str(item.get("article_text", "") or "")[:600]
    item["article_text"] = ""


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
            summary_body = ""

        story_id = int(item.get("story_id") or repository.upsert_story(story, ingestion_run_id=run_id))
        stats["stories_persisted"] += 1
        article_text = str(item.get("article_text", "") or "")
        if not article_text:
            article_text = repository.get_article_text_for_story(story_id)
        repository.upsert_article_snapshot(
            story_id,
            article_text,
            metadata={
                "job": job_name,
                "summary_selected": summary_selected,
                "ingest_score": item.get("ingest_score", ""),
                "ingest_rationale": item.get("ingest_rationale", ""),
                "access_signals": item.get("access_signals", {}),
            },
            paywall_detected=paywall_detected,
            paywall_reason=item["paywall_reason"],
            summary_raw=item["summary_raw"],
            summary_headline=item["summary_headline"],
            summary_body=summary_body,
            summary_model=(
                config["openai"]["summary_model"]
                if (summary_selected and not paywall_detected and summary_body)
                else ""
            ),
            summarized_at=(
                datetime.now(UTC).isoformat()
                if (summary_selected and not paywall_detected and summary_body)
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
    job_name = "fetch_sources"
    repository = repository or get_repository_from_config(config)
    runtime_capture = start_runtime_capture()
    if source_fetcher is None:
        if config.get("development", {}).get("use_canned_sources", False):
            source_fetcher = load_canned_source_links
        else:
            source_fetcher = lambda cfg: collect_enabled_additional_source_links(cfg, repository)
    article_fetcher = article_fetcher or fetch_article_details
    cleanup_result = run_repository_ttl_cleanup(config, repository)
    run_id = repository.create_ingestion_run("additional_source", metadata={"job": job_name})
    stats = {
        "run_id": run_id,
        "ttl_cleanup": cleanup_result,
        "stories_seen": 0,
        "stories_selected_for_fetch": 0,
        "stories_persisted": 0,
        "snapshots_persisted": 0,
        "article_failures": 0,
        "paywall_stories": 0,
        "summary_failures": 0,
        "summary_workers": 0,
        "scored_candidates": 0,
        "summary_candidates": 0,
        "checkpointed_stories": 0,
        "checkpointed_snapshots": 0,
    }
    failures: list[dict] = []
    usage_by_model: dict = {}
    lock = Lock()
    return_payload: dict | None = None
    final_status = "failed"

    try:
        stories = source_fetcher(config)
        stats["stories_seen"] = len(stories)
        _log_ingest_progress(job_name, "stories_collected", stories_seen=stats["stories_seen"])
        prepared = _prepare_ingest_snapshot_candidates(
            stories,
            config=config,
            article_fetcher=article_fetcher,
            stats=stats,
            failures=failures,
            job_name=job_name,
            repository=repository,
            run_id=run_id,
        )
        _log_ingest_progress(job_name, "prepared_candidates", prepared_candidates=len(prepared))
        _log_ingest_progress(job_name, "scoring_started", prepared_candidates=len(prepared))
        selected_candidates = score_for_ingest(
            config,
            prepared,
            usage_by_model,
        )
        stats["scored_candidates"] = len([item for item in prepared if not item["paywall_detected"]])
        stats["summary_candidates"] = len(selected_candidates)
        _log_ingest_progress(
            job_name,
            "scoring_complete",
            scored_candidates=stats["scored_candidates"],
            summary_candidates=stats["summary_candidates"],
        )
        _log_ingest_progress(
            job_name,
            "summaries_started",
            summary_candidates=stats["summary_candidates"],
        )
        stats["summary_workers"] = _run_parallel_ingest_summaries(
            prepared,
            config=config,
            repository=repository,
            usage_by_model=usage_by_model,
            lock=lock,
            job_name=job_name,
        )
        _log_ingest_progress(job_name, "summaries_complete", summary_workers=stats["summary_workers"])
        _log_ingest_progress(
            job_name,
            "persist_started",
            prepared_candidates=len(prepared),
            summary_candidates=stats["summary_candidates"],
        )
        _persist_ingest_snapshots(
            prepared,
            config=config,
            repository=repository,
            run_id=run_id,
            job_name=job_name,
            stats=stats,
            failures=failures,
        )
        _log_ingest_progress(
            job_name,
            "persist_complete",
            stories_persisted=stats["stories_persisted"],
            snapshots_persisted=stats["snapshots_persisted"],
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
        runtime = finish_runtime_capture(runtime_capture)
        if return_payload is not None:
            return_payload["runtime"] = runtime
        repository.complete_ingestion_run(
            run_id,
            status=final_status,
            metadata={
                "job": job_name,
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
                "checkpointed_stories": stats["checkpointed_stories"],
                "checkpointed_snapshots": stats["checkpointed_snapshots"],
                "usage_by_model": usage_by_model,
                "failures": failures,
                "runtime": runtime,
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
    job_name = "fetch_gmail"
    repository = repository or get_repository_from_config(config)
    runtime_capture = start_runtime_capture()
    article_fetcher = article_fetcher or fetch_article_details
    cleanup_result = run_repository_ttl_cleanup(config, repository)
    collect_gmail_links_fn = collect_gmail_links_fn or (
        lambda service, config: collect_live_gmail_links(
            service,
            config,
            extract_links_from_html_fn=extract_links_from_html,
        )
    )
    run_id = repository.create_ingestion_run("gmail", metadata={"job": job_name})
    stats = {
        "run_id": run_id,
        "ttl_cleanup": cleanup_result,
        "stories_seen": 0,
        "stories_selected_for_fetch": 0,
        "stories_persisted": 0,
        "snapshots_persisted": 0,
        "article_failures": 0,
        "paywall_stories": 0,
        "summary_failures": 0,
        "summary_workers": 0,
        "scored_candidates": 0,
        "summary_candidates": 0,
        "checkpointed_stories": 0,
        "checkpointed_snapshots": 0,
    }
    failures: list[dict] = []
    usage_by_model: dict = {}
    lock = Lock()
    return_payload: dict | None = None
    final_status = "failed"

    try:
        stories = collect_gmail_links_fn(service, config)
        stats["stories_seen"] = len(stories)
        _log_ingest_progress(job_name, "stories_collected", stories_seen=stats["stories_seen"])
        stories_to_fetch = score_gmail_stories_for_fetch(
            config,
            stories,
            usage_by_model,
        )
        stats["stories_selected_for_fetch"] = len(stories_to_fetch)
        _log_ingest_progress(
            job_name,
            "fetch_selection_complete",
            stories_seen=stats["stories_seen"],
            stories_selected_for_fetch=stats["stories_selected_for_fetch"],
        )
        prepared = _prepare_ingest_snapshot_candidates(
            stories_to_fetch,
            config=config,
            article_fetcher=article_fetcher,
            stats=stats,
            failures=failures,
            job_name=job_name,
            repository=repository,
            run_id=run_id,
        )
        _log_ingest_progress(job_name, "prepared_candidates", prepared_candidates=len(prepared))
        _log_ingest_progress(job_name, "scoring_started", prepared_candidates=len(prepared))
        selected_candidates = score_for_ingest(
            config,
            prepared,
            usage_by_model,
        )
        stats["scored_candidates"] = len([item for item in prepared if not item["paywall_detected"]])
        stats["summary_candidates"] = len(selected_candidates)
        _log_ingest_progress(
            job_name,
            "scoring_complete",
            scored_candidates=stats["scored_candidates"],
            summary_candidates=stats["summary_candidates"],
        )
        _log_ingest_progress(
            job_name,
            "summaries_started",
            summary_candidates=stats["summary_candidates"],
        )
        stats["summary_workers"] = _run_parallel_ingest_summaries(
            prepared,
            config=config,
            repository=repository,
            usage_by_model=usage_by_model,
            lock=lock,
            job_name=job_name,
        )
        _log_ingest_progress(job_name, "summaries_complete", summary_workers=stats["summary_workers"])
        _log_ingest_progress(
            job_name,
            "persist_started",
            prepared_candidates=len(prepared),
            summary_candidates=stats["summary_candidates"],
        )
        _persist_ingest_snapshots(
            prepared,
            config=config,
            repository=repository,
            run_id=run_id,
            job_name=job_name,
            stats=stats,
            failures=failures,
        )
        _log_ingest_progress(
            job_name,
            "persist_complete",
            stories_persisted=stats["stories_persisted"],
            snapshots_persisted=stats["snapshots_persisted"],
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
        runtime = finish_runtime_capture(runtime_capture)
        if return_payload is not None:
            return_payload["runtime"] = runtime
        repository.complete_ingestion_run(
            run_id,
            status=final_status,
            metadata={
                "job": job_name,
                "ttl_cleanup": cleanup_result,
                "stories_seen": stats["stories_seen"],
                "stories_selected_for_fetch": stats["stories_selected_for_fetch"],
                "stories_persisted": stats["stories_persisted"],
                "snapshots_persisted": stats["snapshots_persisted"],
                "article_failures": stats["article_failures"],
                "paywall_stories": stats["paywall_stories"],
                "summary_failures": stats["summary_failures"],
                "summary_workers": stats["summary_workers"],
                "scored_candidates": stats["scored_candidates"],
                "summary_candidates": stats["summary_candidates"],
                "checkpointed_stories": stats["checkpointed_stories"],
                "checkpointed_snapshots": stats["checkpointed_snapshots"],
                "usage_by_model": usage_by_model,
                "failures": failures,
                "runtime": runtime,
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
    runtime_capture = start_runtime_capture()
    delivery_runner_fn = delivery_runner_fn or (
        lambda cfg, svc: run_delivery_job(cfg, svc, repository=repository)
    )

    stages: dict[str, dict] = {}
    stage_order = ["fetch_gmail", "fetch_sources", "deliver_digest"]
    failures: list[dict] = []

    def run_stage(stage_name: str, stage_fn) -> None:
        stage_runtime_capture = start_runtime_capture()
        emit_event("daily_orchestrator_stage_started", stage=stage_name)
        try:
            stage_result = dict(stage_fn())
        except Exception as exc:
            runtime = finish_runtime_capture(stage_runtime_capture)
            error_type = exc.__class__.__name__
            stages[stage_name] = {
                "status": "failed",
                "error": str(exc),
                "error_type": error_type,
                "runtime": runtime,
            }
            failures.append(
                {
                    "stage": stage_name,
                    "error": str(exc),
                    "error_type": error_type,
                    "runtime": runtime,
                }
            )
            emit_event(
                "daily_orchestrator_stage_failed",
                stage=stage_name,
                error=str(exc),
                error_type=error_type,
                runtime=runtime,
            )
            return

        stage_result.setdefault("runtime", finish_runtime_capture(stage_runtime_capture))
        stages[stage_name] = stage_result
        emit_event(
            "daily_orchestrator_stage_completed",
            stage=stage_name,
            status=stage_result.get("status", "unknown"),
            runtime=stage_result.get("runtime", {}),
        )

    run_stage(
        "fetch_gmail",
        lambda: run_fetch_gmail_job(
            config,
            service,
            repository=repository,
            article_fetcher=article_fetcher,
            collect_gmail_links_fn=collect_gmail_links_fn,
        ),
    )
    run_stage(
        "fetch_sources",
        lambda: run_fetch_sources_job(
            config,
            repository=repository,
            source_fetcher=source_fetcher,
            article_fetcher=article_fetcher,
        ),
    )
    run_stage(
        "deliver_digest",
        lambda: delivery_runner_fn(config, service),
    )

    completed_stages = [
        stage_name
        for stage_name in stage_order
        if stages.get(stage_name, {}).get("status") == "completed"
    ]
    skipped_stages = [
        stage_name
        for stage_name in stage_order
        if stages.get(stage_name, {}).get("status") == "skipped"
    ]
    partial_failure_stages = [
        stage_name
        for stage_name in stage_order
        if stages.get(stage_name, {}).get("status") == "partial_failure"
    ]
    failed_stages = [
        stage_name
        for stage_name in stage_order
        if str(stages.get(stage_name, {}).get("status", "")).strip()
        not in {"completed", "partial_failure", "skipped"}
    ]

    if not failed_stages and not partial_failure_stages:
        status = "completed"
    elif stages.get("deliver_digest", {}).get("status") == "completed":
        status = "partial_failure"
    elif partial_failure_stages:
        status = "partial_failure"
    else:
        status = "failed"

    result = {
        "status": status,
        "stage_order": stage_order,
        "completed_stages": completed_stages,
        "skipped_stages": skipped_stages,
        "partial_failure_stages": partial_failure_stages,
        "failed_stages": failed_stages,
        "stages": stages,
        "failures": failures,
        "runtime": finish_runtime_capture(runtime_capture),
    }
    emit_event("daily_orchestrator", result=result)
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
            require_summary=True,
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
    resolve_digest_recipients_fn=resolve_digest_recipients,
    open_tracking_enabled: bool = True,
    click_tracking_enabled: bool = True,
    use_cached_newsletter: bool = True,
    persist_newsletter: bool = True,
    audience_key: str = DEFAULT_AUDIENCE_KEY,
    delivery_format: str = DEFAULT_SUBSCRIBER_DELIVERY_FORMAT,
    preferred_sources: list[str] | tuple[str, ...] | None = None,
    issue_type_override: str | None = None,
) -> dict:
    repository = repository or get_repository_from_config(config)
    runtime_capture = start_runtime_capture()
    delivery_now = current_delivery_datetime()
    newsletter_date = current_newsletter_date()
    scheduled_issue_type = delivery_issue_type_for_datetime(delivery_now)
    override_issue_type = normalize_issue_type_override(issue_type_override)
    if override_issue_type:
        issue_type = override_issue_type
    elif (service is None or delivery_schedule_ignored()) and scheduled_issue_type == "skipped":
        issue_type = "daily"
    else:
        issue_type = scheduled_issue_type
    delivery_format = normalize_subscriber_delivery_format(delivery_format)
    if issue_type == "skipped":
        runtime = finish_runtime_capture(runtime_capture)
        emit_event(
            "delivery_skipped",
            newsletter_date=newsletter_date,
            reason="weekend_daily_delivery_disabled",
            weekday=delivery_now.weekday(),
        )
        return {
            "status": "skipped",
            "newsletter_date": newsletter_date,
            "issue_type": issue_type,
            "cached_newsletter": False,
            "delivery_format": delivery_format,
            "recipient_source": "",
            "sent_recipients": 0,
            "failed_recipient_count": 0,
            "failed_recipients": [],
            "runtime": runtime,
        }

    config = delivery_config_for_issue(config, issue_type)
    cached_newsletter = (
        repository.get_daily_newsletter(
            newsletter_date,
            audience_key=audience_key,
            issue_type=issue_type,
        )
        if use_cached_newsletter
        else None
    )
    newsletter_cleanup = run_newsletter_ttl_cleanup(config, repository)
    readiness = assess_delivery_readiness(config, repository)
    resolved_recipients, recipient_source = resolve_digest_recipients_fn(config)
    emit_event("delivery_readiness", readiness=readiness)
    emit_event(
        "delivery_recipients",
        recipient_count=len(resolved_recipients),
        recipient_source=recipient_source,
    )
    emit_event(
        "delivery_started",
        audience_key=audience_key,
        issue_type=issue_type,
        delivery_format=delivery_format,
        cached_newsletter_available=cached_newsletter is not None,
        telemetry_enabled=open_tracking_enabled or click_tracking_enabled,
        open_tracking_enabled=open_tracking_enabled,
        click_tracking_enabled=click_tracking_enabled,
        persist_newsletter=persist_newsletter,
        recipient_count=len(resolved_recipients),
        readiness_ok=readiness["ok"],
    )
    if not readiness["ok"] and cached_newsletter is None:
        emit_event(
            "delivery_blocked",
            audience_key=audience_key,
            reason="not_ready_and_no_cached_newsletter",
            readiness=readiness,
        )
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

    public_base_url = resolve_tracking_base_url(config)
    subscriber_settings_url = build_settings_url(public_base_url)

    def build_tracked_send_html(
        daily_newsletter_id: int,
        *,
        html_body: str,
        selected_items: list[dict],
    ) -> tuple[str, int]:
        if not open_tracking_enabled and not click_tracking_enabled:
            return html_body, 0

        if not public_base_url:
            emit_event(
                "delivery_tracking_skipped",
                audience_key=audience_key,
                reason="missing_public_base_url",
                open_tracking_enabled=open_tracking_enabled,
                click_tracking_enabled=click_tracking_enabled,
            )
            return html_body, 0

        open_token = (
            repository.ensure_newsletter_open_token(daily_newsletter_id)
            if open_tracking_enabled
            else ""
        )
        tracked_links = (
            repository.ensure_tracked_links(daily_newsletter_id, selected_items)
            if click_tracking_enabled
            else []
        )
        tracked_link_rows = (
            [
                {
                    **row,
                    "tracked_url": build_click_url(public_base_url, str(row["click_token"])),
                }
                for row in tracked_links
            ]
            if click_tracking_enabled
            else []
        )
        emit_event(
            "delivery_tracking_prepared",
            audience_key=audience_key,
            daily_newsletter_id=daily_newsletter_id,
            tracked_link_count=len(tracked_links),
            tracking_base_url=public_base_url,
            open_tracking_enabled=open_tracking_enabled,
            click_tracking_enabled=click_tracking_enabled,
        )
        return (
            rewrite_newsletter_html_for_tracking(
                html_body,
                tracked_links=tracked_link_rows,
                open_pixel_url=build_open_pixel_url(public_base_url, open_token) if open_token else "",
            ),
            len(tracked_links),
        )

    def send_digest(
        *,
        subject: str,
        body: str,
        html_body: str,
        content: dict,
        selected_items: list[dict],
        daily_newsletter_id: int | None,
    ) -> dict:
        tracked_link_count = 0
        send_body = body
        send_html = html_body
        attachments: list[dict] | None = None
        if daily_newsletter_id is not None:
            send_html, tracked_link_count = build_tracked_send_html(
                daily_newsletter_id,
                html_body=html_body,
                selected_items=selected_items,
            )
        if delivery_format == "pdf":
            issue_slug = "weekly" if issue_type == "weekly" else "daily"
            attachments = [
                {
                    "filename": f"ai-signal-{issue_slug}-{newsletter_date}.pdf",
                    "mime_type": "application/pdf",
                    "content_bytes": render_digest_pdf(
                        content.get("render_groups", {}) if isinstance(content, dict) else {},
                        subject=subject,
                        newsletter_date=newsletter_date,
                        fallback_text=body,
                    ),
                }
            ]
        emit_event(
            "delivery_send_started",
            audience_key=audience_key,
            issue_type=issue_type,
            daily_newsletter_id=daily_newsletter_id,
            delivery_format=delivery_format,
            recipient_count=len(resolved_recipients),
            selected_item_count=len(selected_items),
            tracked_link_count=tracked_link_count,
            telemetry_enabled=(open_tracking_enabled or click_tracking_enabled)
            and daily_newsletter_id is not None,
            open_tracking_enabled=open_tracking_enabled and daily_newsletter_id is not None,
            click_tracking_enabled=click_tracking_enabled and daily_newsletter_id is not None,
            attachment_count=len(attachments or []),
            subject=subject,
        )
        configured_workers = max(
            1,
            int(config.get("limits", {}).get("max_delivery_send_workers", 5) or 5),
        )
        worker_count = min(configured_workers, len(resolved_recipients)) if resolved_recipients else 0
        sent_count = 0
        failed_recipients: list[dict] = []
        pending_sends: list[tuple[str, str]] = []
        for recipient in resolved_recipients:
            message_id_header = build_delivery_message_id(
                newsletter_date=newsletter_date,
                audience_key=audience_key,
                daily_newsletter_id=daily_newsletter_id,
                recipient=recipient,
            )
            emit_event(
                "delivery_recipient_send_started",
                audience_key=audience_key,
                daily_newsletter_id=daily_newsletter_id,
                delivery_format=delivery_format,
                recipient=recipient,
                message_id_header=message_id_header,
            )
            pending_sends.append((recipient, message_id_header))

        send_results: list[tuple[str, str, dict]] = []
        if worker_count <= 1:
            for recipient, message_id_header in pending_sends:
                send_results.append(
                    (
                        recipient,
                        message_id_header,
                        send_email_with_retry_and_dedupe(
                            service,
                            send_email_fn,
                            to_address=recipient,
                            subject=subject,
                            body=send_body,
                            html_body=send_html,
                            attachments=attachments,
                            newsletter_date=newsletter_date,
                            audience_key=audience_key,
                            daily_newsletter_id=daily_newsletter_id,
                            message_id_header=message_id_header,
                        ),
                    )
                )
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(
                        send_email_with_retry_and_dedupe,
                        service,
                        send_email_fn,
                        to_address=recipient,
                        subject=subject,
                        body=send_body,
                        html_body=send_html,
                        attachments=attachments,
                        newsletter_date=newsletter_date,
                        audience_key=audience_key,
                        daily_newsletter_id=daily_newsletter_id,
                        message_id_header=message_id_header,
                    ): (recipient, message_id_header)
                    for recipient, message_id_header in pending_sends
                }
                for future in as_completed(futures):
                    recipient, message_id_header = futures[future]
                    send_results.append((recipient, message_id_header, future.result()))

        for recipient, message_id_header, send_result in send_results:
            for event in list(send_result.get("events", []) or []):
                event_name = str(event.get("event", "")).strip()
                if event_name == "retry":
                    emit_event(
                        "delivery_recipient_send_retry",
                        audience_key=audience_key,
                        daily_newsletter_id=daily_newsletter_id,
                        delivery_format=delivery_format,
                        recipient=recipient,
                        message_id_header=message_id_header,
                        attempt=int(event.get("attempt", 0) or 0),
                        max_attempts=int(event.get("max_attempts", 0) or 0),
                        error=str(event.get("error", "")).strip(),
                        error_type=str(event.get("error_type", "")).strip(),
                        error_status_code=event.get("error_status_code"),
                        error_code=str(event.get("error_code", "")).strip(),
                    )
                elif event_name == "verified_after_error":
                    emit_event(
                        "delivery_recipient_send_verified_after_error",
                        audience_key=audience_key,
                        daily_newsletter_id=daily_newsletter_id,
                        delivery_format=delivery_format,
                        recipient=recipient,
                        message_id_header=message_id_header,
                        attempt=int(event.get("attempt", 0) or 0),
                        error=str(event.get("error", "")).strip(),
                        error_type=str(event.get("error_type", "")).strip(),
                        error_status_code=event.get("error_status_code"),
                        error_code=str(event.get("error_code", "")).strip(),
                    )
                elif event_name == "skipped_existing":
                    emit_event(
                        "delivery_recipient_send_skipped_existing",
                        audience_key=audience_key,
                        daily_newsletter_id=daily_newsletter_id,
                        delivery_format=delivery_format,
                        recipient=recipient,
                        message_id_header=message_id_header,
                        attempt=int(event.get("attempt", 0) or 0),
                    )
                elif event_name == "failed":
                    failed_recipients.append(
                        {
                            "recipient": recipient,
                            "attempts": int(send_result.get("attempts", 0) or 0),
                            "error": str(send_result.get("error", "")).strip(),
                            "error_type": str(send_result.get("error_type", "")).strip(),
                            "error_status_code": send_result.get("error_status_code"),
                            "error_code": str(send_result.get("error_code", "")).strip(),
                            "retryable": bool(send_result.get("retryable", False)),
                            "message_id_header": message_id_header,
                        }
                    )
                    emit_event(
                        "delivery_recipient_send_failed",
                        audience_key=audience_key,
                        daily_newsletter_id=daily_newsletter_id,
                        delivery_format=delivery_format,
                        recipient=recipient,
                        message_id_header=message_id_header,
                        attempt=int(event.get("attempt", 0) or 0),
                        max_attempts=int(event.get("max_attempts", 0) or 0),
                        retryable=bool(event.get("retryable", False)),
                        error=str(event.get("error", "")).strip(),
                        error_type=str(event.get("error_type", "")).strip(),
                        error_status_code=event.get("error_status_code"),
                        error_code=str(event.get("error_code", "")).strip(),
                    )
                elif event_name == "completed":
                    emit_event(
                        "delivery_recipient_send_completed",
                        audience_key=audience_key,
                        daily_newsletter_id=daily_newsletter_id,
                        delivery_format=delivery_format,
                        recipient=recipient,
                        message_id_header=message_id_header,
                        attempt=int(event.get("attempt", 0) or 0),
                    )
            if str(send_result.get("status", "")).strip() == "sent":
                sent_count += 1
        emit_event(
            "delivery_send_completed",
            audience_key=audience_key,
            daily_newsletter_id=daily_newsletter_id,
            delivery_format=delivery_format,
            sent_recipients=sent_count,
            failed_recipients=len(failed_recipients),
            selected_item_count=len(selected_items),
            status="partial_failure" if failed_recipients else "completed",
        )
        return {
            "delivery_format": delivery_format,
            "sent_recipients": sent_count,
            "failed_recipient_count": len(failed_recipients),
            "failed_recipients": failed_recipients,
            "status": "partial_failure" if failed_recipients else "completed",
        }

    def build_newsletter_content(
        *,
        pipeline_result: dict | None = None,
        cached_newsletter: dict | None = None,
    ) -> dict:
        if cached_newsletter is not None:
            content = cached_newsletter.get("content", {}) or {}
            if isinstance(content, dict):
                return content
            return {}

        pipeline_result = pipeline_result or {}
        return {
            "version": 1,
            "render_groups": pipeline_result.get("render_groups", {}) or {},
            "ranked_candidates": int(pipeline_result.get("ranked_candidates", 0) or 0),
            "selected": int(pipeline_result.get("selected", 0) or 0),
            "accepted_items": int(pipeline_result.get("accepted_items", 0) or 0),
        }

    def render_delivery_body(content: dict, fallback_body: str) -> str:
        render_groups = content.get("render_groups", {}) if isinstance(content, dict) else {}
        if not render_groups:
            body = fallback_body
        else:
            body = render_digest_text(render_groups)
        if subscriber_settings_url:
            body = f"Manage your settings: {subscriber_settings_url}\n\n{str(body).strip()}"
        return body

    def render_delivery_html(content: dict, fallback_html: str) -> str:
        render_groups = content.get("render_groups", {}) if isinstance(content, dict) else {}
        if not render_groups:
            return fallback_html
        return render_email_safe_digest_html(
            render_groups,
            settings_url=subscriber_settings_url,
            issue_type=issue_type,
        )

    run_id = repository.create_delivery_run(
        metadata={
            "job": "deliver_digest",
            "readiness": readiness,
            "newsletter_ttl_cleanup": newsletter_cleanup,
            "newsletter_date": newsletter_date,
            "audience_key": audience_key,
            "issue_type": issue_type,
        }
    )
    try:
        if cached_newsletter is not None:
            emit_event(
                "delivery_cached_newsletter_used",
                audience_key=audience_key,
                issue_type=issue_type,
                daily_newsletter_id=int(cached_newsletter["id"]),
                newsletter_date=newsletter_date,
                selected_item_count=len(cached_newsletter.get("selected_items", [])),
            )
            cached_content = build_newsletter_content(cached_newsletter=cached_newsletter)
            digest_body = render_delivery_body(
                cached_content,
                str(cached_newsletter.get("body", "")).strip(),
            )
            delivery_html = render_delivery_html(
                cached_content,
                str(cached_newsletter.get("html_body", "")).strip(),
            )
            digest_body, delivery_html = finalize_delivery_newsletter(digest_body, delivery_html)
            send_result = send_digest(
                subject=cached_newsletter["subject"],
                body=digest_body,
                html_body=delivery_html,
                content=cached_content,
                selected_items=cached_newsletter.get("selected_items", []),
                daily_newsletter_id=int(cached_newsletter["id"]),
            )
            cached_result = {
                "status": send_result["status"],
                "cached_newsletter": True,
                "delivery_format": delivery_format,
                "newsletter_date": newsletter_date,
                "issue_type": issue_type,
                "audience_key": audience_key,
                "daily_newsletter_id": int(cached_newsletter["id"]),
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
                "recipient_source": recipient_source,
                "sent_recipients": send_result["sent_recipients"],
                "failed_recipient_count": send_result["failed_recipient_count"],
                "failed_recipients": send_result["failed_recipients"],
                "digest_subject": cached_newsletter["subject"],
                "digest_body": digest_body,
                "digest_html": delivery_html,
                "email_safe_digest_html": delivery_html,
                "content": cached_content,
            }
            runtime = finish_runtime_capture(runtime_capture)
            cached_result["runtime"] = runtime
            repository.complete_delivery_run(
                run_id,
                status=send_result["status"],
                metadata={
                    "job": "deliver_digest",
                    "readiness": readiness,
                    "newsletter_ttl_cleanup": newsletter_cleanup,
                    "newsletter_date": newsletter_date,
                    "audience_key": audience_key,
                    "issue_type": issue_type,
                    "cached_newsletter": True,
                    "daily_newsletter_id": cached_newsletter["id"],
                    "pipeline_result": cached_result,
                    "runtime": runtime,
                },
            )
            emit_event(
                "delivery_completed",
                audience_key=audience_key,
                issue_type=issue_type,
                cached_newsletter=True,
                daily_newsletter_id=int(cached_newsletter["id"]),
                delivery_format=delivery_format,
                sent_recipients=send_result["sent_recipients"],
                failed_recipients=send_result["failed_recipient_count"],
                status=send_result["status"],
                runtime=runtime,
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
            preferred_sources=preferred_sources,
        )
        emit_event(
            "delivery_pipeline_result",
            audience_key=audience_key,
            pipeline_status=str(pipeline_result.get("status", "")).strip() or "unknown",
            ranked_candidates=int(pipeline_result.get("ranked_candidates", 0) or 0),
            selected=int(pipeline_result.get("selected", 0) or 0),
            accepted_items=int(pipeline_result.get("accepted_items", 0) or 0),
            backfilled_count=int(pipeline_result.get("backfilled_count", 0) or 0),
            skipped_count=int(pipeline_result.get("skipped_count", 0) or 0),
        )
        daily_newsletter_id = None
        if (
            pipeline_result.get("status") == "completed"
            and str(pipeline_result.get("digest_body", "")).strip()
            and str(pipeline_result.get("digest_html", "")).strip()
        ):
            newsletter_content = build_newsletter_content(pipeline_result=pipeline_result)
            digest_body = render_delivery_body(
                newsletter_content,
                str(pipeline_result.get("digest_body", "")).strip(),
            )
            delivery_html = render_delivery_html(
                newsletter_content,
                str(pipeline_result.get("email_safe_digest_html", "")).strip()
                or str(pipeline_result.get("digest_html", "")).strip(),
            )
            digest_body, delivery_html = finalize_delivery_newsletter(digest_body, delivery_html)
            if persist_newsletter:
                processed_candidates = (
                    int(pipeline_result.get("accepted_items", 0) or 0)
                    + int(pipeline_result.get("skipped_count", 0) or 0)
                )
                estimated_cost = estimate_openai_text_cost_usd(
                    pipeline_result.get("usage_by_model", {})
                )
                daily_newsletter_id = repository.upsert_daily_newsletter(
                    newsletter_date=newsletter_date,
                    audience_key=audience_key,
                    issue_type=issue_type,
                    delivery_run_id=run_id,
                    subject=str(pipeline_result.get("digest_subject", "")).strip(),
                    body=digest_body,
                    html_body=delivery_html,
                    content=newsletter_content,
                    selected_items=list(pipeline_result.get("accepted_story_items", [])),
                    metadata={
                        "gmail_links": pipeline_result.get("gmail_links", 0),
                        "additional_source_links": pipeline_result.get(
                            "additional_source_links",
                            0,
                        ),
                        "deduped_links": pipeline_result.get("deduped_links", 0),
                        "eligible_links": pipeline_result.get("eligible_links", 0),
                        "uncapped_eligible_links": pipeline_result.get(
                            "uncapped_eligible_links",
                            pipeline_result.get("eligible_links", 0),
                        ),
                        "weekly_max_stories_per_day": pipeline_result.get(
                            "weekly_max_stories_per_day",
                            0,
                        ),
                        "ranked_candidates": pipeline_result.get("ranked_candidates", 0),
                        "selected": pipeline_result.get("selected", 0),
                        "accepted_items": pipeline_result.get("accepted_items", 0),
                        "processed_candidates": processed_candidates,
                        "backfilled_count": pipeline_result.get("backfilled_count", 0),
                        "skipped_count": pipeline_result.get("skipped_count", 0),
                        "render_groups": pipeline_result.get("render_groups", {}),
                        "usage_by_model": pipeline_result.get("usage_by_model", {}),
                        "total_tokens": pipeline_result.get("total_tokens", 0),
                        "estimated_openai_text_cost_usd": (
                            float(estimated_cost) if estimated_cost is not None else None
                        ),
                        "newsletter_ttl_cleanup": newsletter_cleanup,
                        "issue_type": issue_type,
                    },
                )
                emit_event(
                    "delivery_newsletter_persisted",
                    audience_key=audience_key,
                    issue_type=issue_type,
                    daily_newsletter_id=daily_newsletter_id,
                    newsletter_date=newsletter_date,
                    selected_item_count=len(list(pipeline_result.get("accepted_story_items", []))),
                )
            send_result = send_digest(
                subject=str(pipeline_result.get("digest_subject", "")).strip(),
                body=digest_body,
                html_body=delivery_html,
                content=newsletter_content,
                selected_items=list(pipeline_result.get("accepted_story_items", [])),
                daily_newsletter_id=daily_newsletter_id,
            )
            pipeline_result["sent_recipients"] = send_result["sent_recipients"]
            pipeline_result["failed_recipient_count"] = send_result["failed_recipient_count"]
            pipeline_result["failed_recipients"] = send_result["failed_recipients"]
            pipeline_result["delivery_format"] = delivery_format
            pipeline_result["digest_body"] = digest_body
            pipeline_result["recipient_source"] = recipient_source
            pipeline_result["content"] = newsletter_content
            pipeline_result["delivery_digest_html"] = delivery_html
            pipeline_result["email_safe_digest_html"] = delivery_html
            pipeline_result["daily_newsletter_id"] = daily_newsletter_id
            pipeline_result["audience_key"] = audience_key
            pipeline_result["issue_type"] = issue_type
            if send_result["status"] != "completed":
                pipeline_result["status"] = send_result["status"]
        runtime = finish_runtime_capture(runtime_capture)
        final_status = str(pipeline_result.get("status", "")).strip() or "completed"
        repository.complete_delivery_run(
            run_id,
            status=final_status,
            metadata={
                "job": "deliver_digest",
                "readiness": readiness,
                "newsletter_ttl_cleanup": newsletter_cleanup,
                "newsletter_date": newsletter_date,
                "audience_key": audience_key,
                "issue_type": issue_type,
                "cached_newsletter": False,
                "daily_newsletter_id": daily_newsletter_id,
                "pipeline_result": pipeline_result,
                "runtime": runtime,
            },
        )
        emit_event(
            "delivery_completed",
            audience_key=audience_key,
            issue_type=issue_type,
            cached_newsletter=False,
            daily_newsletter_id=daily_newsletter_id,
            delivery_format=delivery_format,
            sent_recipients=int(pipeline_result.get("sent_recipients", 0) or 0),
            failed_recipients=int(pipeline_result.get("failed_recipient_count", 0) or 0),
            runtime=runtime,
            pipeline_status=str(pipeline_result.get("status", "")).strip() or "unknown",
        )
        return {
            "run_id": run_id,
            "newsletter_date": newsletter_date,
            "audience_key": audience_key,
            "issue_type": issue_type,
            "cached_newsletter": False,
            "delivery_format": delivery_format,
            "status": final_status,
            "runtime": runtime,
            **pipeline_result,
        }
    except Exception as exc:
        runtime = finish_runtime_capture(runtime_capture)
        repository.complete_delivery_run(
            run_id,
            status="failed",
            metadata={
                "job": "deliver_digest",
                "readiness": readiness,
                "newsletter_ttl_cleanup": newsletter_cleanup,
                "newsletter_date": newsletter_date,
                "audience_key": audience_key,
                "issue_type": issue_type,
                "error": str(exc),
                "runtime": runtime,
            },
        )
        emit_event(
            "delivery_failed",
            audience_key=audience_key,
            issue_type=issue_type,
            error=str(exc),
            runtime=runtime,
        )
        raise
