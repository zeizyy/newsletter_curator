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
            self._run_migrations(connection)

    def _run_migrations(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied_versions = {
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        migrations = {1: self._migration_v1}
        for version, migration in migrations.items():
            if version in applied_versions:
                continue
            migration(connection)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, utc_now()),
            )

    def _migration_v1(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(source_type, source_name)
            );

            CREATE TABLE ingestion_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE delivery_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE fetched_stories (
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

            CREATE INDEX idx_fetched_stories_source_type ON fetched_stories(source_type);
            CREATE INDEX idx_fetched_stories_source_name ON fetched_stories(source_name);
            CREATE INDEX idx_fetched_stories_published_at ON fetched_stories(published_at);

            CREATE TABLE article_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                story_id INTEGER NOT NULL UNIQUE REFERENCES fetched_stories(id) ON DELETE CASCADE,
                article_text TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE user_source_selections (
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
        self, story_id: int, article_text: str, metadata: dict | None = None
    ) -> int:
        now = utc_now()
        payload = json.dumps(metadata or {}, sort_keys=True)
        content_hash = hashlib.sha1(article_text.encode("utf-8", errors="ignore")).hexdigest()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO article_snapshots (story_id, article_text, content_hash, fetched_at, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(story_id)
                DO UPDATE SET
                    article_text = excluded.article_text,
                    content_hash = excluded.content_hash,
                    fetched_at = excluded.fetched_at,
                    metadata_json = excluded.metadata_json
                """,
                (story_id, article_text, content_hash, now, payload),
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
                snap.fetched_at AS article_fetched_at
            FROM fetched_stories fs
            LEFT JOIN article_snapshots snap ON snap.story_id = fs.id
            {where_clause}
            ORDER BY COALESCE(fs.published_at, fs.first_seen_at) DESC, fs.id DESC
        """
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

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
                row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
                counts[table] = int(row["count"])
        return counts
