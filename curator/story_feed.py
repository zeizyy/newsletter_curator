from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from . import config as config_module

RECENT_STORY_WINDOW_HOURS = 24


def resolve_database_path(config: dict) -> Path:
    database_cfg = config.get("database", {})
    database_path = Path(str(database_cfg.get("path", "data/newsletter_curator.sqlite3")))
    if not database_path.is_absolute():
        database_path = config_module.BASE_DIR / database_path
    return database_path


@contextmanager
def connect_readonly(database_path: Path):
    resolved_path = Path(database_path).resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Repository database not found at {resolved_path}")
    uri = f"file:{quote(str(resolved_path), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _normalize_nullable_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_story_row(row: sqlite3.Row) -> dict:
    return {
        "id": int(row["id"]),
        "story_key": str(row["story_key"] or ""),
        "source_type": str(row["source_type"] or ""),
        "source_name": str(row["source_name"] or ""),
        "subject": str(row["subject"] or ""),
        "url": str(row["url"] or ""),
        "canonical_url": str(row["canonical_url"] or ""),
        "anchor_text": str(row["anchor_text"] or ""),
        "context": str(row["context"] or ""),
        "category": str(row["category"] or ""),
        "published_at": _normalize_nullable_text(row["published_at"]),
        "first_seen_at": str(row["first_seen_at"] or ""),
        "last_seen_at": str(row["last_seen_at"] or ""),
        "effective_timestamp": str(row["effective_timestamp"] or ""),
        "summary": str(row["summary"] or ""),
        "summary_headline": str(row["summary_headline"] or ""),
        "summary_body": str(row["summary_body"] or ""),
        "article_fetched_at": _normalize_nullable_text(row["article_fetched_at"]),
        "paywall_detected": bool(row["paywall_detected"]),
        "paywall_reason": _normalize_nullable_text(row["paywall_reason"]),
        "summarized_at": _normalize_nullable_text(row["summarized_at"]),
    }


def list_recent_story_feed(
    config: dict,
    *,
    now: datetime | None = None,
    window_hours: int = RECENT_STORY_WINDOW_HOURS,
) -> dict:
    current_time = now or datetime.now(UTC)
    cutoff = (current_time - timedelta(hours=window_hours)).isoformat()
    database_path = resolve_database_path(config)
    query = """
        SELECT
            fs.id,
            fs.story_key,
            fs.source_type,
            fs.source_name,
            fs.subject,
            fs.url,
            fs.canonical_url,
            fs.anchor_text,
            fs.context,
            fs.category,
            fs.published_at,
            fs.summary,
            fs.first_seen_at,
            fs.last_seen_at,
            COALESCE(NULLIF(fs.published_at, ''), fs.first_seen_at) AS effective_timestamp,
            snap.fetched_at AS article_fetched_at,
            snap.paywall_detected,
            snap.paywall_reason,
            snap.summary_headline,
            snap.summary_body,
            snap.summarized_at
        FROM fetched_stories fs
        LEFT JOIN article_snapshots snap ON snap.story_id = fs.id
        WHERE COALESCE(NULLIF(fs.published_at, ''), fs.first_seen_at) >= ?
        ORDER BY COALESCE(NULLIF(fs.published_at, ''), fs.first_seen_at) DESC, fs.id DESC
    """
    with connect_readonly(database_path) as connection:
        rows = connection.execute(query, (cutoff,)).fetchall()
    stories = [_normalize_story_row(row) for row in rows]
    return {
        "generated_at": current_time.isoformat(),
        "window_hours": window_hours,
        "story_count": len(stories),
        "stories": stories,
    }
