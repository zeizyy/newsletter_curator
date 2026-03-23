from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
            "access_evaluation_runs": {
                "id",
                "evaluator",
                "status",
                "started_at",
                "finished_at",
                "scope_json",
                "metadata_json",
            },
            "access_evaluation_labels": {
                "id",
                "evaluation_run_id",
                "story_id",
                "classifier_status",
                "agent_label",
                "rationale",
                "created_at",
            },
            "daily_newsletters": {
                "id",
                "newsletter_date",
                "delivery_run_id",
                "subject",
                "body",
                "html_body",
                "selected_items_json",
                "metadata_json",
                "created_at",
                "updated_at",
            },
            "preview_generations": {
                "id",
                "newsletter_date",
                "status",
                "generation_token",
                "started_at",
                "finished_at",
                "last_error",
                "updated_at",
            },
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
                "servability_status",
                "detector_version",
                "classifier_signals_json",
                "summary_raw",
                "summary_headline",
                "summary_body",
                "summary_model",
                "summarized_at",
            },
            "user_source_selections": {"id", "source_id", "enabled", "updated_at"},
            "newsletter_telemetry": {
                "id",
                "daily_newsletter_id",
                "open_token",
                "created_at",
            },
            "tracked_links": {
                "id",
                "daily_newsletter_id",
                "click_token",
                "target_url",
                "story_title",
                "created_at",
            },
            "newsletter_open_events": {
                "id",
                "daily_newsletter_id",
                "open_token",
                "opened_at",
                "user_agent",
                "ip_address",
            },
            "newsletter_click_events": {
                "id",
                "daily_newsletter_id",
                "tracked_link_id",
                "click_token",
                "clicked_at",
                "user_agent",
                "ip_address",
            },
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
            "newsletter_click_events",
            "newsletter_open_events",
            "tracked_links",
            "newsletter_telemetry",
            "fetched_stories",
            "delivery_runs",
            "access_evaluation_labels",
            "access_evaluation_runs",
            "daily_newsletters",
            "preview_generations",
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

            CREATE TABLE IF NOT EXISTS access_evaluation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evaluator TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                scope_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS access_evaluation_labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evaluation_run_id INTEGER NOT NULL REFERENCES access_evaluation_runs(id) ON DELETE CASCADE,
                story_id INTEGER NOT NULL REFERENCES fetched_stories(id) ON DELETE CASCADE,
                classifier_status TEXT NOT NULL,
                agent_label TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(evaluation_run_id, story_id)
            );

            CREATE TABLE IF NOT EXISTS daily_newsletters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                newsletter_date TEXT NOT NULL UNIQUE,
                delivery_run_id INTEGER REFERENCES delivery_runs(id) ON DELETE SET NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                html_body TEXT NOT NULL,
                selected_items_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS preview_generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                newsletter_date TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                generation_token TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                last_error TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
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
                servability_status TEXT NOT NULL DEFAULT 'candidate',
                detector_version TEXT NOT NULL DEFAULT '',
                classifier_signals_json TEXT NOT NULL DEFAULT '{}',
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

            CREATE TABLE IF NOT EXISTS newsletter_telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_newsletter_id INTEGER NOT NULL UNIQUE REFERENCES daily_newsletters(id) ON DELETE CASCADE,
                open_token TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tracked_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_newsletter_id INTEGER NOT NULL REFERENCES daily_newsletters(id) ON DELETE CASCADE,
                click_token TEXT NOT NULL UNIQUE,
                target_url TEXT NOT NULL,
                story_title TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(daily_newsletter_id, target_url)
            );

            CREATE TABLE IF NOT EXISTS newsletter_open_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_newsletter_id INTEGER NOT NULL REFERENCES daily_newsletters(id) ON DELETE CASCADE,
                open_token TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                user_agent TEXT NOT NULL DEFAULT '',
                ip_address TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS newsletter_click_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_newsletter_id INTEGER NOT NULL REFERENCES daily_newsletters(id) ON DELETE CASCADE,
                tracked_link_id INTEGER NOT NULL REFERENCES tracked_links(id) ON DELETE CASCADE,
                click_token TEXT NOT NULL,
                clicked_at TEXT NOT NULL,
                user_agent TEXT NOT NULL DEFAULT '',
                ip_address TEXT NOT NULL DEFAULT ''
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

    def create_access_evaluation_run(
        self,
        evaluator: str,
        *,
        scope: dict | None = None,
        metadata: dict | None = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO access_evaluation_runs (
                    evaluator,
                    status,
                    started_at,
                    scope_json,
                    metadata_json
                )
                VALUES (?, 'running', ?, ?, ?)
                """,
                (
                    evaluator,
                    utc_now(),
                    json.dumps(scope or {}, sort_keys=True),
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )
            return int(cursor.lastrowid)

    def complete_access_evaluation_run(
        self,
        run_id: int,
        *,
        status: str,
        metadata: dict | None = None,
    ) -> None:
        with self.connect() as connection:
            current = connection.execute(
                "SELECT metadata_json FROM access_evaluation_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            merged_metadata = json.loads(current["metadata_json"]) if current else {}
            if metadata:
                merged_metadata.update(metadata)
            connection.execute(
                """
                UPDATE access_evaluation_runs
                SET status = ?, finished_at = ?, metadata_json = ?
                WHERE id = ?
                """,
                (status, utc_now(), json.dumps(merged_metadata, sort_keys=True), run_id),
            )

    def list_access_evaluation_runs(self, *, limit: int = 20) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, evaluator, status, started_at, finished_at, scope_json, metadata_json
                FROM access_evaluation_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        runs: list[dict] = []
        for row in rows:
            payload = dict(row)
            payload["scope"] = json.loads(str(payload.pop("scope_json", "") or "{}"))
            payload["metadata"] = json.loads(str(payload.pop("metadata_json", "") or "{}"))
            runs.append(payload)
        return runs

    def get_access_evaluation_metrics(self, evaluation_run_id: int) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS labels_reviewed,
                    SUM(CASE WHEN agent_label = 'uncertain' THEN 1 ELSE 0 END) AS uncertain_labels,
                    SUM(
                        CASE
                            WHEN agent_label != 'uncertain'
                             AND classifier_status = 'blocked'
                             AND agent_label = 'blocked'
                            THEN 1 ELSE 0
                        END
                    ) AS true_positives,
                    SUM(
                        CASE
                            WHEN agent_label != 'uncertain'
                             AND classifier_status = 'blocked'
                             AND agent_label = 'servable'
                            THEN 1 ELSE 0
                        END
                    ) AS false_positives,
                    SUM(
                        CASE
                            WHEN agent_label != 'uncertain'
                             AND classifier_status != 'blocked'
                             AND agent_label = 'blocked'
                            THEN 1 ELSE 0
                        END
                    ) AS false_negatives,
                    SUM(
                        CASE
                            WHEN agent_label != 'uncertain'
                             AND classifier_status != 'blocked'
                             AND agent_label = 'servable'
                            THEN 1 ELSE 0
                        END
                    ) AS true_negatives
                FROM access_evaluation_labels
                WHERE evaluation_run_id = ?
                """,
                (evaluation_run_id,),
            ).fetchone()
        metrics = {
            "labels_reviewed": int(row["labels_reviewed"] or 0),
            "uncertain_labels": int(row["uncertain_labels"] or 0),
            "true_positives": int(row["true_positives"] or 0),
            "false_positives": int(row["false_positives"] or 0),
            "false_negatives": int(row["false_negatives"] or 0),
            "true_negatives": int(row["true_negatives"] or 0),
        }
        reviewed_with_decision = (
            metrics["true_positives"]
            + metrics["false_positives"]
            + metrics["false_negatives"]
            + metrics["true_negatives"]
        )
        metrics["evaluated_labels"] = reviewed_with_decision
        return metrics

    def list_access_evaluation_run_summaries(self, *, limit: int = 20) -> list[dict]:
        runs = self.list_access_evaluation_runs(limit=limit)
        summaries: list[dict] = []
        for run in runs:
            summary = dict(run)
            summary["metrics"] = self.get_access_evaluation_metrics(int(run["id"]))
            summaries.append(summary)
        return summaries

    def record_access_evaluation_label(
        self,
        evaluation_run_id: int,
        *,
        story_id: int,
        classifier_status: str,
        agent_label: str,
        rationale: str = "",
    ) -> int:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO access_evaluation_labels (
                    evaluation_run_id,
                    story_id,
                    classifier_status,
                    agent_label,
                    rationale,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(evaluation_run_id, story_id)
                DO UPDATE SET
                    classifier_status = excluded.classifier_status,
                    agent_label = excluded.agent_label,
                    rationale = excluded.rationale,
                    created_at = excluded.created_at
                """,
                (
                    evaluation_run_id,
                    story_id,
                    classifier_status,
                    agent_label,
                    rationale,
                    utc_now(),
                ),
            )
            row = connection.execute(
                """
                SELECT id
                FROM access_evaluation_labels
                WHERE evaluation_run_id = ? AND story_id = ?
                """,
                (evaluation_run_id, story_id),
            ).fetchone()
            return int(row["id"])

    def list_access_evaluation_labels(self, evaluation_run_id: int) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    ael.id,
                    ael.evaluation_run_id,
                    ael.story_id,
                    ael.classifier_status,
                    ael.agent_label,
                    ael.rationale,
                    ael.created_at,
                    fs.url,
                    fs.source_name,
                    fs.source_type
                FROM access_evaluation_labels ael
                JOIN fetched_stories fs ON fs.id = ael.story_id
                WHERE ael.evaluation_run_id = ?
                ORDER BY ael.id ASC
                """,
                (evaluation_run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_daily_newsletter(self, newsletter_date: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    newsletter_date,
                    delivery_run_id,
                    subject,
                    body,
                    html_body,
                    selected_items_json,
                    metadata_json,
                    created_at,
                    updated_at
                FROM daily_newsletters
                WHERE newsletter_date = ?
                LIMIT 1
                """,
                (newsletter_date,),
            ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["selected_items"] = json.loads(
            str(payload.pop("selected_items_json", "") or "[]")
        )
        payload["metadata"] = json.loads(str(payload.pop("metadata_json", "") or "{}"))
        return payload

    def list_daily_newsletters(self, *, limit: int = 30) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    newsletter_date,
                    delivery_run_id,
                    subject,
                    selected_items_json,
                    metadata_json,
                    created_at,
                    updated_at
                FROM daily_newsletters
                ORDER BY newsletter_date DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        newsletters: list[dict] = []
        for row in rows:
            payload = dict(row)
            selected_items = json.loads(str(payload.pop("selected_items_json", "") or "[]"))
            payload["metadata"] = json.loads(str(payload.pop("metadata_json", "") or "{}"))
            payload["selected_items_count"] = len(selected_items)
            newsletters.append(payload)
        return newsletters

    def get_preview_generation(self, newsletter_date: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    newsletter_date,
                    status,
                    generation_token,
                    started_at,
                    finished_at,
                    last_error,
                    updated_at
                FROM preview_generations
                WHERE newsletter_date = ?
                LIMIT 1
                """,
                (newsletter_date,),
            ).fetchone()
        return dict(row) if row is not None else None

    def acquire_preview_generation(
        self,
        newsletter_date: str,
        *,
        stale_after_seconds: int = 900,
    ) -> dict:
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        stale_cutoff = (now_dt - timedelta(seconds=max(1, stale_after_seconds))).isoformat()
        generation_token = secrets.token_hex(12)

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO preview_generations (
                    newsletter_date,
                    status,
                    generation_token,
                    started_at,
                    finished_at,
                    last_error,
                    updated_at
                )
                VALUES (?, 'running', ?, ?, NULL, '', ?)
                ON CONFLICT(newsletter_date)
                DO UPDATE SET
                    status = 'running',
                    generation_token = excluded.generation_token,
                    started_at = excluded.started_at,
                    finished_at = NULL,
                    last_error = '',
                    updated_at = excluded.updated_at
                WHERE preview_generations.status != 'running'
                   OR preview_generations.started_at < ?
                """,
                (
                    newsletter_date,
                    generation_token,
                    now,
                    now,
                    stale_cutoff,
                ),
            )
            row = connection.execute(
                """
                SELECT
                    id,
                    newsletter_date,
                    status,
                    generation_token,
                    started_at,
                    finished_at,
                    last_error,
                    updated_at
                FROM preview_generations
                WHERE newsletter_date = ?
                LIMIT 1
                """,
                (newsletter_date,),
            ).fetchone()

        payload = dict(row) if row is not None else {}
        payload["acquired"] = bool(
            payload
            and payload.get("status") == "running"
            and payload.get("generation_token") == generation_token
        )
        return payload

    def complete_preview_generation(
        self,
        newsletter_date: str,
        generation_token: str,
        *,
        status: str,
        last_error: str = "",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE preview_generations
                SET status = ?,
                    finished_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE newsletter_date = ?
                  AND generation_token = ?
                """,
                (
                    status,
                    utc_now(),
                    last_error,
                    utc_now(),
                    newsletter_date,
                    generation_token,
                ),
            )

    def upsert_daily_newsletter(
        self,
        *,
        newsletter_date: str,
        subject: str,
        body: str,
        html_body: str,
        selected_items: list[dict] | None = None,
        metadata: dict | None = None,
        delivery_run_id: int | None = None,
    ) -> int:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO daily_newsletters (
                    newsletter_date,
                    delivery_run_id,
                    subject,
                    body,
                    html_body,
                    selected_items_json,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(newsletter_date)
                DO UPDATE SET
                    delivery_run_id = excluded.delivery_run_id,
                    subject = excluded.subject,
                    body = excluded.body,
                    html_body = excluded.html_body,
                    selected_items_json = excluded.selected_items_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    newsletter_date,
                    delivery_run_id,
                    subject,
                    body,
                    html_body,
                    json.dumps(selected_items or [], sort_keys=True),
                    json.dumps(metadata or {}, sort_keys=True),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT id FROM daily_newsletters WHERE newsletter_date = ?",
                (newsletter_date,),
            ).fetchone()
            return int(row["id"])

    def delete_daily_newsletters_older_than(self, cutoff_newsletter_date: str) -> dict[str, int]:
        with self.connect() as connection:
            newsletter_row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM daily_newsletters
                WHERE newsletter_date < ?
                """,
                (cutoff_newsletter_date,),
            ).fetchone()
            newsletters_deleted = int(newsletter_row["count"])

            preview_row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM preview_generations
                WHERE newsletter_date < ?
                """,
                (cutoff_newsletter_date,),
            ).fetchone()
            preview_generations_deleted = int(preview_row["count"])

            telemetry_row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM newsletter_telemetry
                WHERE daily_newsletter_id IN (
                    SELECT id FROM daily_newsletters WHERE newsletter_date < ?
                )
                """,
                (cutoff_newsletter_date,),
            ).fetchone()
            telemetry_deleted = int(telemetry_row["count"])

            tracked_links_row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM tracked_links
                WHERE daily_newsletter_id IN (
                    SELECT id FROM daily_newsletters WHERE newsletter_date < ?
                )
                """,
                (cutoff_newsletter_date,),
            ).fetchone()
            tracked_links_deleted = int(tracked_links_row["count"])

            open_events_row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM newsletter_open_events
                WHERE daily_newsletter_id IN (
                    SELECT id FROM daily_newsletters WHERE newsletter_date < ?
                )
                """,
                (cutoff_newsletter_date,),
            ).fetchone()
            open_events_deleted = int(open_events_row["count"])

            click_events_row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM newsletter_click_events
                WHERE daily_newsletter_id IN (
                    SELECT id FROM daily_newsletters WHERE newsletter_date < ?
                )
                """,
                (cutoff_newsletter_date,),
            ).fetchone()
            click_events_deleted = int(click_events_row["count"])

            connection.execute(
                "DELETE FROM preview_generations WHERE newsletter_date < ?",
                (cutoff_newsletter_date,),
            )
            connection.execute(
                "DELETE FROM daily_newsletters WHERE newsletter_date < ?",
                (cutoff_newsletter_date,),
            )

        return {
            "newsletters_deleted": newsletters_deleted,
            "preview_generations_deleted": preview_generations_deleted,
            "telemetry_deleted": telemetry_deleted,
            "tracked_links_deleted": tracked_links_deleted,
            "open_events_deleted": open_events_deleted,
            "click_events_deleted": click_events_deleted,
        }

    def _run_row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        payload = dict(row)
        metadata_json = str(payload.pop("metadata_json", "") or "{}")
        payload["metadata"] = json.loads(metadata_json)
        return payload

    def ensure_newsletter_open_token(self, daily_newsletter_id: int) -> str:
        open_token = hashlib.sha1(f"open|{daily_newsletter_id}".encode("utf-8")).hexdigest()[:24]
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO newsletter_telemetry (daily_newsletter_id, open_token, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(daily_newsletter_id)
                DO UPDATE SET open_token = excluded.open_token
                """,
                (daily_newsletter_id, open_token, utc_now()),
            )
        return open_token

    def ensure_tracked_links(
        self,
        daily_newsletter_id: int,
        selected_items: list[dict] | None = None,
    ) -> list[dict]:
        selected_items = selected_items or []
        with self.connect() as connection:
            for item in selected_items:
                target_url = str(item.get("url", "")).strip()
                if not target_url:
                    continue
                click_token = hashlib.sha1(
                    f"click|{daily_newsletter_id}|{canonicalize_url(target_url)}".encode("utf-8")
                ).hexdigest()[:24]
                connection.execute(
                    """
                    INSERT INTO tracked_links (
                        daily_newsletter_id,
                        click_token,
                        target_url,
                        story_title,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(daily_newsletter_id, target_url)
                    DO UPDATE SET
                        story_title = excluded.story_title
                    """,
                    (
                        daily_newsletter_id,
                        click_token,
                        target_url,
                        str(item.get("title", "")).strip(),
                        utc_now(),
                    ),
                )
            rows = connection.execute(
                """
                SELECT id, daily_newsletter_id, click_token, target_url, story_title, created_at
                FROM tracked_links
                WHERE daily_newsletter_id = ?
                ORDER BY id ASC
                """,
                (daily_newsletter_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_newsletter_open(
        self,
        open_token: str,
        *,
        user_agent: str = "",
        ip_address: str = "",
    ) -> dict | None:
        with self.connect() as connection:
            telemetry_row = connection.execute(
                """
                SELECT daily_newsletter_id
                FROM newsletter_telemetry
                WHERE open_token = ?
                LIMIT 1
                """,
                (open_token,),
            ).fetchone()
            if telemetry_row is None:
                return None
            daily_newsletter_id = int(telemetry_row["daily_newsletter_id"])
            connection.execute(
                """
                INSERT INTO newsletter_open_events (
                    daily_newsletter_id,
                    open_token,
                    opened_at,
                    user_agent,
                    ip_address
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (daily_newsletter_id, open_token, utc_now(), user_agent, ip_address),
            )
        return {"daily_newsletter_id": daily_newsletter_id}

    def record_newsletter_click(
        self,
        click_token: str,
        *,
        user_agent: str = "",
        ip_address: str = "",
    ) -> dict | None:
        with self.connect() as connection:
            link_row = connection.execute(
                """
                SELECT id, daily_newsletter_id, target_url
                FROM tracked_links
                WHERE click_token = ?
                LIMIT 1
                """,
                (click_token,),
            ).fetchone()
            if link_row is None:
                return None
            tracked_link_id = int(link_row["id"])
            daily_newsletter_id = int(link_row["daily_newsletter_id"])
            target_url = str(link_row["target_url"])
            connection.execute(
                """
                INSERT INTO newsletter_click_events (
                    daily_newsletter_id,
                    tracked_link_id,
                    click_token,
                    clicked_at,
                    user_agent,
                    ip_address
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    daily_newsletter_id,
                    tracked_link_id,
                    click_token,
                    utc_now(),
                    user_agent,
                    ip_address,
                ),
            )
        return {
            "daily_newsletter_id": daily_newsletter_id,
            "tracked_link_id": tracked_link_id,
            "target_url": target_url,
        }

    def _event_visitor_key_sql(self, alias: str) -> str:
        return (
            "CASE "
            f"WHEN COALESCE(NULLIF({alias}.ip_address, ''), NULLIF({alias}.user_agent, '')) IS NULL "
            f"THEN 'event:' || {alias}.id "
            f"ELSE COALESCE(NULLIF({alias}.ip_address, ''), '-') || '|' || "
            f"COALESCE(NULLIF({alias}.user_agent, ''), '-') "
            "END"
        )

    def list_newsletter_analytics(self, *, limit: int = 14) -> list[dict]:
        open_visitor_key = self._event_visitor_key_sql("noe")
        click_visitor_key = self._event_visitor_key_sql("nce")
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    dn.id,
                    dn.newsletter_date,
                    dn.subject,
                    dn.created_at,
                    dn.selected_items_json,
                    COALESCE(opens.total_opens, 0) AS total_opens,
                    COALESCE(opens.unique_opens, 0) AS unique_opens,
                    COALESCE(clicks.total_clicks, 0) AS total_clicks,
                    COALESCE(clicks.unique_clicks, 0) AS unique_clicks,
                    (
                        SELECT tl.story_title
                        FROM tracked_links tl
                        JOIN newsletter_click_events nce_top ON nce_top.tracked_link_id = tl.id
                        WHERE tl.daily_newsletter_id = dn.id
                        GROUP BY tl.id, tl.story_title
                        ORDER BY COUNT(nce_top.id) DESC, tl.id ASC
                        LIMIT 1
                    ) AS top_story_title,
                    (
                        SELECT tl.target_url
                        FROM tracked_links tl
                        JOIN newsletter_click_events nce_top ON nce_top.tracked_link_id = tl.id
                        WHERE tl.daily_newsletter_id = dn.id
                        GROUP BY tl.id, tl.target_url
                        ORDER BY COUNT(nce_top.id) DESC, tl.id ASC
                        LIMIT 1
                    ) AS top_story_url,
                    (
                        SELECT COUNT(nce_top.id)
                        FROM tracked_links tl
                        JOIN newsletter_click_events nce_top ON nce_top.tracked_link_id = tl.id
                        WHERE tl.daily_newsletter_id = dn.id
                        GROUP BY tl.id
                        ORDER BY COUNT(nce_top.id) DESC, tl.id ASC
                        LIMIT 1
                    ) AS top_story_clicks
                FROM daily_newsletters dn
                LEFT JOIN (
                    SELECT
                        noe.daily_newsletter_id,
                        COUNT(*) AS total_opens,
                        COUNT(DISTINCT {open_visitor_key}) AS unique_opens
                    FROM newsletter_open_events noe
                    GROUP BY noe.daily_newsletter_id
                ) AS opens ON opens.daily_newsletter_id = dn.id
                LEFT JOIN (
                    SELECT
                        nce.daily_newsletter_id,
                        COUNT(*) AS total_clicks,
                        COUNT(DISTINCT {click_visitor_key}) AS unique_clicks
                    FROM newsletter_click_events nce
                    GROUP BY nce.daily_newsletter_id
                ) AS clicks ON clicks.daily_newsletter_id = dn.id
                ORDER BY dn.newsletter_date DESC, dn.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        analytics: list[dict] = []
        for row in rows:
            payload = dict(row)
            selected_items = json.loads(str(payload.pop("selected_items_json", "") or "[]"))
            unique_opens = int(payload["unique_opens"])
            unique_clicks = int(payload["unique_clicks"])
            payload["selected_items_count"] = len(selected_items)
            payload["click_through_rate"] = (
                round((unique_clicks / unique_opens) * 100, 1) if unique_opens else None
            )
            analytics.append(payload)
        return analytics

    def get_newsletter_aggregate_stats(
        self,
        *,
        trailing_days: tuple[int, ...] = (7, 30),
    ) -> list[dict]:
        open_visitor_key = self._event_visitor_key_sql("noe")
        click_visitor_key = self._event_visitor_key_sql("nce")
        today = datetime.now(UTC).date()
        windows: list[dict] = []

        with self.connect() as connection:
            for days in trailing_days:
                since_date = (today - timedelta(days=max(days - 1, 0))).isoformat()
                row = connection.execute(
                    f"""
                    WITH scoped_newsletters AS (
                        SELECT id, newsletter_date
                        FROM daily_newsletters
                        WHERE newsletter_date >= ?
                    ),
                    open_stats AS (
                        SELECT
                            noe.daily_newsletter_id,
                            COUNT(*) AS total_opens,
                            COUNT(DISTINCT {open_visitor_key}) AS unique_opens
                        FROM newsletter_open_events noe
                        WHERE noe.daily_newsletter_id IN (SELECT id FROM scoped_newsletters)
                        GROUP BY noe.daily_newsletter_id
                    ),
                    click_stats AS (
                        SELECT
                            nce.daily_newsletter_id,
                            COUNT(*) AS total_clicks,
                            COUNT(DISTINCT {click_visitor_key}) AS unique_clicks
                        FROM newsletter_click_events nce
                        WHERE nce.daily_newsletter_id IN (SELECT id FROM scoped_newsletters)
                        GROUP BY nce.daily_newsletter_id
                    )
                    SELECT
                        (SELECT COUNT(*) FROM scoped_newsletters) AS newsletters,
                        COALESCE((SELECT SUM(total_opens) FROM open_stats), 0) AS total_opens,
                        COALESCE((SELECT SUM(unique_opens) FROM open_stats), 0) AS unique_opens,
                        COALESCE((SELECT SUM(total_clicks) FROM click_stats), 0) AS total_clicks,
                        COALESCE((SELECT SUM(unique_clicks) FROM click_stats), 0) AS unique_clicks
                    """,
                    (since_date,),
                ).fetchone()
                payload = dict(row or {})
                unique_opens = int(payload.get("unique_opens", 0) or 0)
                unique_clicks = int(payload.get("unique_clicks", 0) or 0)
                payload["days"] = days
                payload["since_date"] = since_date
                payload["click_through_rate"] = (
                    round((unique_clicks / unique_opens) * 100, 1) if unique_opens else None
                )
                windows.append(payload)
        return windows

    def list_top_clicked_stories(
        self,
        *,
        trailing_days: int = 30,
        limit: int = 10,
    ) -> list[dict]:
        click_visitor_key = self._event_visitor_key_sql("nce")
        since_date = (datetime.now(UTC).date() - timedelta(days=max(trailing_days - 1, 0))).isoformat()
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    tl.story_title,
                    tl.target_url,
                    COUNT(nce.id) AS total_clicks,
                    COUNT(DISTINCT {click_visitor_key}) AS unique_clicks,
                    COUNT(DISTINCT dn.newsletter_date) AS newsletters_clicked,
                    MAX(dn.newsletter_date) AS last_newsletter_date
                FROM newsletter_click_events nce
                JOIN tracked_links tl ON tl.id = nce.tracked_link_id
                JOIN daily_newsletters dn ON dn.id = nce.daily_newsletter_id
                WHERE dn.newsletter_date >= ?
                GROUP BY tl.story_title, tl.target_url
                ORDER BY total_clicks DESC, unique_clicks DESC, last_newsletter_date DESC
                LIMIT ?
                """,
                (since_date, limit),
            ).fetchall()
        return [dict(row) for row in rows]

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
        servability_status: str = "candidate",
        detector_version: str = "",
        classifier_signals: dict | None = None,
        summary_raw: str = "",
        summary_headline: str = "",
        summary_body: str = "",
        summary_model: str = "",
        summarized_at: str | None = None,
    ) -> int:
        now = utc_now()
        payload = json.dumps(metadata or {}, sort_keys=True)
        classifier_signals_json = json.dumps(classifier_signals or {}, sort_keys=True)
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
                    servability_status,
                    detector_version,
                    classifier_signals_json,
                    summary_raw,
                    summary_headline,
                    summary_body,
                    summary_model,
                    summarized_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(story_id)
                DO UPDATE SET
                    article_text = excluded.article_text,
                    content_hash = excluded.content_hash,
                    fetched_at = excluded.fetched_at,
                    metadata_json = excluded.metadata_json,
                    paywall_detected = excluded.paywall_detected,
                    paywall_reason = excluded.paywall_reason,
                    servability_status = excluded.servability_status,
                    detector_version = excluded.detector_version,
                    classifier_signals_json = excluded.classifier_signals_json,
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
                    servability_status,
                    detector_version,
                    classifier_signals_json,
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
        require_summary: bool = False,
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
        if require_summary:
            conditions.append("COALESCE(NULLIF(TRIM(snap.summary_body), ''), '') != ''")
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
                snap.servability_status,
                snap.detector_version,
                snap.classifier_signals_json,
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
        stories: list[dict] = []
        for row in rows:
            payload = dict(row)
            payload["classifier_signals"] = json.loads(
                str(payload.pop("classifier_signals_json", "") or "{}")
            )
            stories.append(payload)
        return stories

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
            "access_evaluation_runs",
            "access_evaluation_labels",
            "daily_newsletters",
            "preview_generations",
            "newsletter_telemetry",
            "tracked_links",
            "newsletter_open_events",
            "newsletter_click_events",
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
