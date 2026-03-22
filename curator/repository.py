from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    cleaned = parsed._replace(query=urlencode(query, doseq=True), fragment="")
    return urlunparse(cleaned)


def story_key(source_type: str, source_name: str, url: str) -> str:
    raw = f"{source_type.strip()}|{source_name.strip()}|{canonicalize_url(url)}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


@dataclass
class SQLiteRepository:
    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            if self._needs_schema_reset(connection):
                self._drop_managed_tables(connection)
            self._create_schema(connection)

    def _table_exists(self, connection: sqlite3.Connection, table_name: str) -> bool:
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _table_columns(self, connection: sqlite3.Connection, table_name: str) -> set[str]:
        if not self._table_exists(connection, table_name):
            return set()
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row["name"]) for row in rows}

    def _needs_schema_reset(self, connection: sqlite3.Connection) -> bool:
        if self._table_exists(connection, "schema_migrations"):
            return True

        expected_columns = {
            "sources": {"id", "source_type", "source_name", "created_at", "updated_at"},
            "ingestion_runs": {"id", "source_type", "status", "started_at", "finished_at", "metadata_json"},
            "delivery_runs": {"id", "status", "started_at", "finished_at", "metadata_json"},
            "fetched_stories": {
                "id",
                "story_key",
                "source_id",
                "ingestion_run_id",
                "source_type",
                "source_name",
                "subject",
                "url",
                "canonical_url",
                "anchor_text",
                "context",
                "category",
                "published_at",
                "summary",
                "raw_payload_json",
                "first_seen_at",
                "last_seen_at",
            },
            "article_snapshots": {
                "id",
                "story_id",
                "article_text",
                "content_hash",
                "fetched_at",
                "metadata_json",
                "paywall_detected",
                "paywall_reason",
                "summary_raw",
                "summary_headline",
                "summary_body",
                "summary_model",
                "summarized_at",
            },
            "user_source_selections": {"id", "source_id", "enabled", "updated_at"},
        }
        for table_name, expected in expected_columns.items():
            columns = self._table_columns(connection, table_name)
            if columns and not expected.issubset(columns):
                return True
        return False

    def _drop_managed_tables(self, connection: sqlite3.Connection) -> None:
        for table_name in [
            "schema_migrations",
            "article_snapshots",
            "user_source_selections",
            "fetched_stories",
            "delivery_runs",
            "ingestion_runs",
            "sources",
        ]:
            connection.execute(f"DROP TABLE IF EXISTS {table_name}")

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(source_type, source_name)
            );

            CREATE TABLE IF NOT EXISTS ingestion_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS delivery_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS fetched_stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                story_key TEXT NOT NULL UNIQUE,
                source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                ingestion_run_id INTEGER REFERENCES ingestion_runs(id) ON DELETE SET NULL,
                source_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL,
                canonical_url TEXT NOT NULL,
                anchor_text TEXT NOT NULL DEFAULT '',
                context TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                summary TEXT NOT NULL DEFAULT '',
                raw_payload_json TEXT NOT NULL DEFAULT '{}',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_fetched_stories_source_type ON fetched_stories(source_type);
            CREATE INDEX IF NOT EXISTS idx_fetched_stories_source_name ON fetched_stories(source_name);
            CREATE INDEX IF NOT EXISTS idx_fetched_stories_published_at ON fetched_stories(published_at);

            CREATE TABLE IF NOT EXISTS article_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                story_id INTEGER NOT NULL UNIQUE REFERENCES fetched_stories(id) ON DELETE CASCADE,
                article_text TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                paywall_detected INTEGER NOT NULL DEFAULT 0,
                paywall_reason TEXT NOT NULL DEFAULT '',
                summary_raw TEXT NOT NULL DEFAULT '',
                summary_headline TEXT NOT NULL DEFAULT '',
                summary_body TEXT NOT NULL DEFAULT '',
                summary_model TEXT NOT NULL DEFAULT '',
                summarized_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_source_selections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL UNIQUE REFERENCES sources(id) ON DELETE CASCADE,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            """
        )

    def create_ingestion_run(self, source_type: str, metadata: dict | None = None) -> int:
        payload = json.dumps(metadata or {}, sort_keys=True)
        started_at = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO ingestion_runs (source_type, status, started_at, metadata_json)
                VALUES (?, 'running', ?, ?)
                """,
                (source_type, started_at, payload),
            )
            return int(cursor.lastrowid)

    def complete_ingestion_run(
        self, run_id: int, *, status: str, metadata: dict | None = None
    ) -> None:
        with self.connect() as connection:
            current = connection.execute(
                "SELECT metadata_json FROM ingestion_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            merged_metadata = json.loads(current["metadata_json"]) if current else {}
            if metadata:
                merged_metadata.update(metadata)
            connection.execute(
                """
                UPDATE ingestion_runs
                SET status = ?, finished_at = ?, metadata_json = ?
                WHERE id = ?
                """,
                (status, utc_now(), json.dumps(merged_metadata, sort_keys=True), run_id),
            )

    def create_delivery_run(self, metadata: dict | None = None) -> int:
        payload = json.dumps(metadata or {}, sort_keys=True)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO delivery_runs (status, started_at, metadata_json)
                VALUES ('running', ?, ?)
                """,
                (utc_now(), payload),
            )
            return int(cursor.lastrowid)

    def complete_delivery_run(
        self, run_id: int, *, status: str, metadata: dict | None = None
    ) -> None:
        with self.connect() as connection:
            current = connection.execute(
                "SELECT metadata_json FROM delivery_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            merged_metadata = json.loads(current["metadata_json"]) if current else {}
            if metadata:
                merged_metadata.update(metadata)
            connection.execute(
                """
                UPDATE delivery_runs
                SET status = ?, finished_at = ?, metadata_json = ?
                WHERE id = ?
                """,
                (status, utc_now(), json.dumps(merged_metadata, sort_keys=True), run_id),
            )

    def get_latest_ingestion_run(
        self, source_type: str, *, status: str | None = None
    ) -> dict | None:
        conditions = ["source_type = ?"]
        params: list[str] = [source_type]
        if status:
            conditions.append("status = ?")
            params.append(status)
        where_clause = " AND ".join(conditions)
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT id, source_type, status, started_at, finished_at, metadata_json
                FROM ingestion_runs
                WHERE {where_clause}
                ORDER BY id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self._run_row_to_dict(row)

    def get_latest_delivery_run(self) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, status, started_at, finished_at, metadata_json
                FROM delivery_runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return self._run_row_to_dict(row)

    def _run_row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        payload = dict(row)
        metadata_json = str(payload.pop("metadata_json", "") or "{}")
        payload["metadata"] = json.loads(metadata_json)
        return payload

    def upsert_source(self, *, source_type: str, source_name: str) -> int:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sources (source_type, source_name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_type, source_name)
                DO UPDATE SET updated_at = excluded.updated_at
                """,
                (source_type, source_name, now, now),
            )
            row = connection.execute(
                "SELECT id FROM sources WHERE source_type = ? AND source_name = ?",
                (source_type, source_name),
            ).fetchone()
            return int(row["id"])

    def upsert_story(self, story: dict, *, ingestion_run_id: int | None = None) -> int:
        source_type = str(story.get("source_type", "")).strip() or "unknown"
        source_name = str(story.get("source_name", story.get("from", ""))).strip() or "unknown"
        raw_url = str(story.get("url", "")).strip()
        if not raw_url:
            raise ValueError("story.url is required")
        canonical_url = canonicalize_url(raw_url)
        key = story_key(source_type, source_name, canonical_url)
        source_id = self.upsert_source(source_type=source_type, source_name=source_name)
        now = utc_now()
        raw_payload = json.dumps(story, sort_keys=True)

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO fetched_stories (
                    story_key,
                    source_id,
                    ingestion_run_id,
                    source_type,
                    source_name,
                    subject,
                    url,
                    canonical_url,
                    anchor_text,
                    context,
                    category,
                    published_at,
                    summary,
                    raw_payload_json,
                    first_seen_at,
                    last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(story_key)
                DO UPDATE SET
                    source_id = excluded.source_id,
                    ingestion_run_id = excluded.ingestion_run_id,
                    subject = excluded.subject,
                    url = excluded.url,
                    anchor_text = excluded.anchor_text,
                    context = excluded.context,
                    category = excluded.category,
                    published_at = excluded.published_at,
                    summary = excluded.summary,
                    raw_payload_json = excluded.raw_payload_json,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    key,
                    source_id,
                    ingestion_run_id,
                    source_type,
                    source_name,
                    str(story.get("subject", "")).strip(),
                    raw_url,
                    canonical_url,
                    str(story.get("anchor_text", "")).strip(),
                    str(story.get("context", "")).strip(),
                    str(story.get("category", "")).strip(),
                    str(story.get("published_at", story.get("date", ""))).strip(),
                    str(story.get("summary", "")).strip(),
                    raw_payload,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT id FROM fetched_stories WHERE story_key = ?",
                (key,),
            ).fetchone()
            return int(row["id"])

    def upsert_article_snapshot(
        self,
        story_id: int,
        article_text: str,
        metadata: dict | None = None,
        *,
        paywall_detected: bool = False,
        paywall_reason: str = "",
        summary_raw: str = "",
        summary_headline: str = "",
        summary_body: str = "",
        summary_model: str = "",
        summarized_at: str | None = None,
    ) -> int:
        now = utc_now()
        payload = json.dumps(metadata or {}, sort_keys=True)
        content_hash = hashlib.sha1(article_text.encode("utf-8", errors="ignore")).hexdigest()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO article_snapshots (
                    story_id,
                    article_text,
                    content_hash,
                    fetched_at,
                    metadata_json,
                    paywall_detected,
                    paywall_reason,
                    summary_raw,
                    summary_headline,
                    summary_body,
                    summary_model,
                    summarized_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(story_id)
                DO UPDATE SET
                    article_text = excluded.article_text,
                    content_hash = excluded.content_hash,
                    fetched_at = excluded.fetched_at,
                    metadata_json = excluded.metadata_json,
                    paywall_detected = excluded.paywall_detected,
                    paywall_reason = excluded.paywall_reason,
                    summary_raw = excluded.summary_raw,
                    summary_headline = excluded.summary_headline,
                    summary_body = excluded.summary_body,
                    summary_model = excluded.summary_model,
                    summarized_at = excluded.summarized_at
                """,
                (
                    story_id,
                    article_text,
                    content_hash,
                    now,
                    payload,
                    int(paywall_detected),
                    paywall_reason,
                    summary_raw,
                    summary_headline,
                    summary_body,
                    summary_model,
                    summarized_at,
                ),
            )
            row = connection.execute(
                "SELECT id FROM article_snapshots WHERE story_id = ?",
                (story_id,),
            ).fetchone()
            return int(row["id"])

    def set_source_selection(self, *, source_type: str, source_name: str, enabled: bool) -> int:
        source_id = self.upsert_source(source_type=source_type, source_name=source_name)
        return self.set_source_selection_by_id(source_id, enabled=enabled)

    def set_source_selection_by_id(self, source_id: int, *, enabled: bool) -> int:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_source_selections (source_id, enabled, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_id)
                DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (source_id, int(enabled), utc_now()),
            )
            row = connection.execute(
                "SELECT id FROM user_source_selections WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            return int(row["id"])

    def list_sources_with_selection(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.id AS source_id,
                    s.source_type,
                    s.source_name,
                    uss.enabled
                FROM sources s
                LEFT JOIN user_source_selections uss ON uss.source_id = s.id
                ORDER BY s.source_type, s.source_name
                """
            ).fetchall()
        return [
            {
                "id": int(row["source_id"]),
                "source_type": row["source_type"],
                "source_name": row["source_name"],
                "enabled": True if row["enabled"] is None else bool(row["enabled"]),
            }
            for row in rows
        ]

    def list_enabled_sources(self) -> list[dict]:
        rows = self.list_sources_with_selection()
        return [
            {
                "source_type": row["source_type"],
                "source_name": row["source_name"],
                "enabled": row["enabled"],
            }
            for row in rows
        ]

    def list_stories(
        self,
        *,
        source_type: str | None = None,
        source_name: str | None = None,
        published_after: str | None = None,
        include_paywalled: bool = True,
    ) -> list[dict]:
        conditions = []
        params: list[str] = []
        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)
        if source_name:
            conditions.append("source_name = ?")
            params.append(source_name)
        if published_after:
            conditions.append("published_at >= ?")
            params.append(published_after)
        if not include_paywalled:
            conditions.append("(snap.paywall_detected IS NULL OR snap.paywall_detected = 0)")
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
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
                snap.article_text,
                snap.content_hash,
                snap.fetched_at AS article_fetched_at,
                snap.paywall_detected,
                snap.paywall_reason,
                snap.summary_raw,
                snap.summary_headline,
                snap.summary_body,
                snap.summary_model,
                snap.summarized_at
            FROM fetched_stories fs
            LEFT JOIN article_snapshots snap ON snap.story_id = fs.id
            {where_clause}
            ORDER BY COALESCE(fs.published_at, fs.first_seen_at) DESC, fs.id DESC
        """
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def delete_stories_older_than(
        self,
        cutoff: str,
        *,
        source_types: list[str] | None = None,
    ) -> dict[str, int]:
        source_types = source_types or []
        conditions = ["COALESCE(NULLIF(published_at, ''), first_seen_at) < ?"]
        params: list[str] = [cutoff]
        if source_types:
            placeholders = ", ".join("?" for _ in source_types)
            conditions.append(f"source_type IN ({placeholders})")
            params.extend(source_types)
        where_clause = " AND ".join(conditions)

        with self.connect() as connection:
            story_row = connection.execute(
                f"SELECT COUNT(*) AS count FROM fetched_stories WHERE {where_clause}",
                params,
            ).fetchone()
            stories_deleted = int(story_row["count"])

            snapshot_row = connection.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM article_snapshots
                WHERE story_id IN (
                    SELECT id FROM fetched_stories WHERE {where_clause}
                )
                """,
                params,
            ).fetchone()
            snapshots_deleted = int(snapshot_row["count"])

            connection.execute(f"DELETE FROM fetched_stories WHERE {where_clause}", params)

            source_row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM sources
                WHERE id NOT IN (SELECT DISTINCT source_id FROM fetched_stories)
                """
            ).fetchone()
            orphaned_sources_deleted = int(source_row["count"])
            connection.execute(
                """
                DELETE FROM sources
                WHERE id NOT IN (SELECT DISTINCT source_id FROM fetched_stories)
                """
            )

        return {
            "stories_deleted": stories_deleted,
            "snapshots_deleted": snapshots_deleted,
            "orphaned_sources_deleted": orphaned_sources_deleted,
        }

    def get_table_counts(self) -> dict[str, int]:
        tables = [
            "schema_migrations",
            "sources",
            "ingestion_runs",
            "delivery_runs",
            "fetched_stories",
            "article_snapshots",
            "user_source_selections",
        ]
        counts = {}
        with self.connect() as connection:
            for table in tables:
                if not self._table_exists(connection, table):
                    counts[table] = 0
                    continue
                row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
                counts[table] = int(row["count"])
        return counts
