from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

from .config import BASE_DIR
from .content import trim_context
from .observability import emit_event
from .repository import SQLiteRepository


def _coerce_additional_source_story(story: object) -> dict[str, object]:
    if isinstance(story, dict):
        return dict(story)
    if is_dataclass(story):
        return asdict(story)
    return {}


def _load_additional_source_builder(script_path: str):
    module_name = (
        f"_newsletter_additional_sources_{hashlib.sha1(script_path.encode('utf-8')).hexdigest()}"
    )
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load additional sources module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    builder = getattr(module, "build_daily_digest_payload", None)
    if not callable(builder):
        raise AttributeError(
            f"Additional sources module {script_path} must export build_daily_digest_payload"
        )
    return builder


def collect_additional_source_links(config: dict, *, base_dir: str | os.PathLike[str] | None = None) -> list[dict]:
    source_cfg = config.get("additional_sources", {})
    if not source_cfg.get("enabled", False):
        return []

    root_dir = Path(base_dir or BASE_DIR)
    script_path = source_cfg.get(
        "script_path", "skills/daily-news-curator/scripts/build_daily_digest.py"
    )
    if not os.path.isabs(script_path):
        script_path = str(root_dir / script_path)
    if not os.path.exists(script_path):
        print(f"Additional sources script not found: {script_path}")
        return []

    hours = int(source_cfg.get("hours", 24))
    top_per_category = int(source_cfg.get("top_per_category", 5))
    max_total = int(source_cfg.get("max_total", 20))
    timeout_seconds = max(int(source_cfg.get("command_timeout_seconds", 300) or 300), 1)
    max_feed_workers = max(int(source_cfg.get("max_feed_workers", 5) or 5), 1)
    feeds_file = source_cfg.get("feeds_file", "")
    if feeds_file:
        if not os.path.isabs(feeds_file):
            feeds_file = str(root_dir / feeds_file)

    emit_event(
        "additional_source_collection_started",
        script_path=script_path,
        timeout_seconds=timeout_seconds,
        hours=hours,
        top_per_category=top_per_category,
        max_total=max_total,
        max_feed_workers=max_feed_workers,
        custom_feeds=bool(feeds_file),
    )
    try:
        builder = _load_additional_source_builder(script_path)
        result = builder(
            feeds_file=feeds_file or None,
            hours=hours,
            top_per_category=top_per_category,
            max_total=max_total,
            max_feed_workers=max_feed_workers,
            total_timeout_seconds=timeout_seconds,
            event_logger=lambda event, **payload: emit_event(
                event,
                script_path=script_path,
                **payload,
            ),
        )
    except Exception as exc:
        emit_event(
            "additional_source_collection_failed",
            script_path=script_path,
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
        print("Additional source ingestion failed.")
        print(str(exc))
        return []

    stories = result.get("stories", [])
    failures = result.get("failures", [])
    if not isinstance(stories, list):
        emit_event(
            "additional_source_collection_invalid_output",
            script_path=script_path,
            output_type=type(stories).__name__,
        )
        print("Additional source ingestion returned non-list stories.")
        return []

    links = []
    for story in stories:
        story_data = _coerce_additional_source_story(story)
        if not story_data:
            continue
        url = str(story_data.get("url", "")).strip()
        if not url:
            continue
        title = str(story_data.get("title", "")).strip()
        source = str(story_data.get("source", "")).strip() or "Additional Source"
        category = str(story_data.get("category", "")).strip()
        published_raw = story_data.get("published_at", "")
        if isinstance(published_raw, datetime):
            published_at = published_raw.isoformat()
        else:
            published_at = str(published_raw).strip()
        summary = str(story_data.get("summary", "")).strip()
        context = trim_context(summary or title or url)
        links.append(
            {
                "subject": f"[{category or 'general'}] {title or source}",
                "from": source,
                "source_name": source,
                "source_type": "additional_source",
                "date": published_at,
                "published_at": published_at,
                "url": url,
                "anchor_text": title or source,
                "context": context,
            }
        )
    emit_event(
        "additional_source_collection_completed",
        script_path=script_path,
        story_count=len(stories),
        link_count=len(links),
        failure_count=len(failures) if isinstance(failures, list) else 0,
    )
    return links


def load_canned_source_links(
    config: dict,
    *,
    base_dir: str | os.PathLike[str] | None = None,
) -> list[dict]:
    development_cfg = config.get("development", {})
    canned_file = development_cfg.get("canned_sources_file", "tests/fixtures/canned_sources.json")
    root_dir = Path(base_dir or BASE_DIR)
    canned_path = Path(canned_file)
    if not canned_path.is_absolute():
        canned_path = root_dir / canned_path
    with canned_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("canned sources file must contain a JSON list")
    return [dict(item) for item in data if isinstance(item, dict)]


def collect_repository_source_links(
    config: dict,
    *,
    repository: SQLiteRepository | None = None,
    base_dir: str | os.PathLike[str] | None = None,
) -> list[dict]:
    source_cfg = config.get("additional_sources", {})
    if not source_cfg.get("enabled", False):
        return []

    database_path = config.get("database", {}).get("path", "data/newsletter_curator.sqlite3")
    root_dir = Path(base_dir or BASE_DIR)
    if not Path(database_path).is_absolute():
        database_path = root_dir / database_path

    repository = repository or SQLiteRepository(Path(database_path))
    repository.initialize()

    cutoff = datetime.now(UTC) - timedelta(hours=int(source_cfg.get("hours", 24)))
    stories = repository.list_stories(
        source_type="additional_source",
        published_after=cutoff.isoformat(),
        include_paywalled=False,
        require_summary=True,
    )
    enabled_map = {
        (row["source_type"], row["source_name"]): row["enabled"]
        for row in repository.list_enabled_sources()
    }
    links = []
    for story in stories:
        if not enabled_map.get((story["source_type"], story["source_name"]), True):
            continue
        title = str(story.get("anchor_text", "")).strip() or str(story.get("subject", "")).strip()
        source_name = str(story.get("source_name", "")).strip() or "Additional Source"
        category = str(story.get("category", "")).strip()
        summary = str(story.get("summary", "")).strip()
        context = trim_context(story.get("context") or summary or title or story.get("url", ""))
        links.append(
            {
                "subject": str(story.get("subject", "")).strip() or f"[{category or 'general'}] {title or source_name}",
                "from": source_name,
                "source_name": source_name,
                "source_type": "additional_source",
                "date": str(story.get("published_at", "")).strip(),
                "published_at": str(story.get("published_at", "")).strip(),
                "url": str(story.get("url", "")).strip(),
                "anchor_text": title or source_name,
                "context": context,
                "category": category,
                "summary": summary,
                "article_text": str(story.get("article_text", "") or ""),
                "summary_raw": str(story.get("summary_raw", "") or ""),
                "summary_headline": str(story.get("summary_headline", "") or ""),
                "summary_body": str(story.get("summary_body", "") or ""),
            }
        )
    return links
