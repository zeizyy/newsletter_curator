from __future__ import annotations

import email.utils
import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .config import is_default_enabled_source_name


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


DEFAULT_AUDIENCE_KEY = "default"
DEFAULT_SUBSCRIBER_DELIVERY_FORMAT = "email"
SUPPORTED_SUBSCRIBER_DELIVERY_FORMATS = {
    DEFAULT_SUBSCRIBER_DELIVERY_FORMAT,
    "pdf",
}


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    cleaned = parsed._replace(query=urlencode(query, doseq=True), fragment="")
    return urlunparse(cleaned)


def hash_secret_token(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8", errors="ignore")).hexdigest()


def normalize_subscriber_delivery_format(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_SUBSCRIBER_DELIVERY_FORMATS:
        return normalized
    return DEFAULT_SUBSCRIBER_DELIVERY_FORMAT


class SchemaResetRequiredError(RuntimeError):
    pass


def story_key(source_type: str, source_name: str, url: str) -> str:
    raw = f"{source_type.strip()}|{source_name.strip()}|{canonicalize_url(url)}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def normalize_email_datetime(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None
    if parsed is None:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


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

    def initialize(self, *, allow_schema_reset: bool = False) -> None:
        with self.connect() as connection:
            self._migrate_compatible_schema(connection)
            reset_reason = self._schema_reset_reason(connection)
            if reset_reason and not allow_schema_reset:
                raise SchemaResetRequiredError(
                    f"Database schema mismatch detected for {self.path}. "
                    f"Managed tables were not reset automatically because that would purge data. "
                    f"Reason: {reset_reason}. "
                    "Opt in explicitly with database.allow_schema_reset=true or "
                    "CURATOR_ALLOW_SCHEMA_RESET=1 if you want to recreate the managed tables."
                )
            if reset_reason:
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
        return self._schema_reset_reason(connection) is not None

    def _schema_reset_reason(self, connection: sqlite3.Connection) -> str | None:
        if self._table_exists(connection, "schema_migrations"):
            return "legacy schema_migrations table is present"

        expected_columns = {
            "sources": {"id", "source_type", "source_name", "created_at", "updated_at"},
            "ingestion_runs": {"id", "source_type", "status", "started_at", "finished_at", "metadata_json"},
            "delivery_runs": {"id", "status", "started_at", "finished_at", "metadata_json"},
            "daily_newsletters": {
                "id",
                "newsletter_date",
                "audience_key",
                "issue_type",
                "delivery_run_id",
                "subject",
                "body",
                "html_body",
                "content_json",
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
                "email_sent_at",
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
            "subscribers": {
                "id",
                "email_address",
                "created_at",
                "updated_at",
                "last_login_at",
            },
            "subscriber_login_tokens": {
                "id",
                "subscriber_id",
                "token_hash",
                "created_at",
                "expires_at",
                "consumed_at",
                "request_ip",
                "user_agent",
            },
            "subscriber_sessions": {
                "id",
                "subscriber_id",
                "session_token_hash",
                "created_at",
                "expires_at",
                "last_seen_at",
                "revoked_at",
                "ip_address",
                "user_agent",
            },
            "subscriber_profiles": {
                "subscriber_id",
                "persona_text",
                "delivery_format",
                "preferred_sources_json",
                "created_at",
                "updated_at",
            },
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
                missing = sorted(expected - columns)
                return f"{table_name} is missing expected columns: {', '.join(missing)}"
        return None

    def _migrate_compatible_schema(self, connection: sqlite3.Connection) -> None:
        self._migrate_daily_newsletters_audience_keys(connection)
        self._migrate_daily_newsletters_issue_types(connection)
        self._migrate_subscriber_profiles_delivery_format(connection)
        self._migrate_fetched_stories_email_sent_at(connection)

    def _migrate_fetched_stories_email_sent_at(self, connection: sqlite3.Connection) -> None:
        columns = self._table_columns(connection, "fetched_stories")
        if not columns or "email_sent_at" in columns:
            return
        connection.execute("ALTER TABLE fetched_stories ADD COLUMN email_sent_at TEXT")
        rows = connection.execute(
            """
            SELECT id, raw_payload_json
            FROM fetched_stories
            WHERE source_type = 'gmail'
            """
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(str(row["raw_payload_json"] or "{}"))
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                continue
            email_sent_at = normalize_email_datetime(
                str(payload.get("email_sent_at") or payload.get("date") or "")
            )
            if not email_sent_at:
                continue
            connection.execute(
                "UPDATE fetched_stories SET email_sent_at = ? WHERE id = ?",
                (email_sent_at, row["id"]),
            )

    def _migrate_daily_newsletters_audience_keys(self, connection: sqlite3.Connection) -> None:
        columns = self._table_columns(connection, "daily_newsletters")
        if not columns or "audience_key" in columns:
            return

        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                f"""
                CREATE TABLE daily_newsletters_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    newsletter_date TEXT NOT NULL,
                    audience_key TEXT NOT NULL DEFAULT '{DEFAULT_AUDIENCE_KEY}',
                    delivery_run_id INTEGER REFERENCES delivery_runs(id) ON DELETE SET NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    html_body TEXT NOT NULL,
                    content_json TEXT NOT NULL DEFAULT '{{}}',
                    selected_items_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{{}}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(newsletter_date, audience_key)
                );

                INSERT INTO daily_newsletters_migrated (
                    id,
                    newsletter_date,
                    audience_key,
                    delivery_run_id,
                    subject,
                    body,
                    html_body,
                    content_json,
                    selected_items_json,
                    metadata_json,
                    created_at,
                    updated_at
                )
                SELECT
                    id,
                    newsletter_date,
                    '{DEFAULT_AUDIENCE_KEY}',
                    delivery_run_id,
                    subject,
                    body,
                    html_body,
                    content_json,
                    selected_items_json,
                    metadata_json,
                    created_at,
                    updated_at
                FROM daily_newsletters;
                """
            )

            dependent_tables = {
                "newsletter_telemetry": """
                    CREATE TABLE newsletter_telemetry_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        daily_newsletter_id INTEGER NOT NULL UNIQUE REFERENCES daily_newsletters(id) ON DELETE CASCADE,
                        open_token TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL
                    )
                """,
                "tracked_links": """
                    CREATE TABLE tracked_links_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        daily_newsletter_id INTEGER NOT NULL REFERENCES daily_newsletters(id) ON DELETE CASCADE,
                        click_token TEXT NOT NULL UNIQUE,
                        target_url TEXT NOT NULL,
                        story_title TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        UNIQUE(daily_newsletter_id, target_url)
                    )
                """,
                "newsletter_open_events": """
                    CREATE TABLE newsletter_open_events_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        daily_newsletter_id INTEGER NOT NULL REFERENCES daily_newsletters(id) ON DELETE CASCADE,
                        open_token TEXT NOT NULL,
                        opened_at TEXT NOT NULL,
                        user_agent TEXT NOT NULL DEFAULT '',
                        ip_address TEXT NOT NULL DEFAULT ''
                    )
                """,
                "newsletter_click_events": """
                    CREATE TABLE newsletter_click_events_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        daily_newsletter_id INTEGER NOT NULL REFERENCES daily_newsletters(id) ON DELETE CASCADE,
                        tracked_link_id INTEGER NOT NULL REFERENCES tracked_links(id) ON DELETE CASCADE,
                        click_token TEXT NOT NULL,
                        clicked_at TEXT NOT NULL,
                        user_agent TEXT NOT NULL DEFAULT '',
                        ip_address TEXT NOT NULL DEFAULT ''
                    )
                """,
            }

            for table_name, create_sql in dependent_tables.items():
                if not self._table_exists(connection, table_name):
                    continue
                connection.execute(create_sql)
                column_names = [
                    str(row["name"])
                    for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
                ]
                joined_columns = ", ".join(column_names)
                connection.execute(
                    f"""
                    INSERT INTO {table_name}_migrated ({joined_columns})
                    SELECT {joined_columns}
                    FROM {table_name}
                    """
                )

            for table_name in [
                "newsletter_click_events",
                "newsletter_open_events",
                "tracked_links",
                "newsletter_telemetry",
            ]:
                if self._table_exists(connection, table_name):
                    connection.execute(f"DROP TABLE {table_name}")

            connection.execute("DROP TABLE daily_newsletters")
            connection.execute("ALTER TABLE daily_newsletters_migrated RENAME TO daily_newsletters")

            for table_name in [
                "newsletter_telemetry",
                "tracked_links",
                "newsletter_open_events",
                "newsletter_click_events",
            ]:
                migrated_table = f"{table_name}_migrated"
                if self._table_exists(connection, migrated_table):
                    connection.execute(
                        f"ALTER TABLE {migrated_table} RENAME TO {table_name}"
                    )
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    def _migrate_subscriber_profiles_delivery_format(self, connection: sqlite3.Connection) -> None:
        columns = self._table_columns(connection, "subscriber_profiles")
        if not columns or "delivery_format" in columns:
            return
        connection.execute(
            """
            ALTER TABLE subscriber_profiles
            ADD COLUMN delivery_format TEXT NOT NULL DEFAULT 'email'
            """
        )
        connection.execute(
            """
            UPDATE subscriber_profiles
            SET delivery_format = 'email'
            WHERE TRIM(COALESCE(delivery_format, '')) = ''
            """
        )

    def _migrate_daily_newsletters_issue_types(self, connection: sqlite3.Connection) -> None:
        columns = self._table_columns(connection, "daily_newsletters")
        if not columns or "issue_type" in columns:
            return

        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                CREATE TABLE daily_newsletters_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    newsletter_date TEXT NOT NULL,
                    audience_key TEXT NOT NULL DEFAULT 'default',
                    issue_type TEXT NOT NULL DEFAULT 'daily',
                    delivery_run_id INTEGER REFERENCES delivery_runs(id) ON DELETE SET NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    html_body TEXT NOT NULL,
                    content_json TEXT NOT NULL DEFAULT '{}',
                    selected_items_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(newsletter_date, audience_key, issue_type)
                );

                INSERT INTO daily_newsletters_migrated (
                    id,
                    newsletter_date,
                    audience_key,
                    issue_type,
                    delivery_run_id,
                    subject,
                    body,
                    html_body,
                    content_json,
                    selected_items_json,
                    metadata_json,
                    created_at,
                    updated_at
                )
                SELECT
                    id,
                    newsletter_date,
                    audience_key,
                    CASE
                        WHEN json_valid(metadata_json) THEN
                            COALESCE(NULLIF(json_extract(metadata_json, '$.issue_type'), ''), 'daily')
                        ELSE 'daily'
                    END,
                    delivery_run_id,
                    subject,
                    body,
                    html_body,
                    content_json,
                    selected_items_json,
                    metadata_json,
                    created_at,
                    updated_at
                FROM daily_newsletters;
                """
            )

            dependent_tables = {
                "newsletter_telemetry": """
                    CREATE TABLE newsletter_telemetry_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        daily_newsletter_id INTEGER NOT NULL UNIQUE REFERENCES daily_newsletters(id) ON DELETE CASCADE,
                        open_token TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL
                    )
                """,
                "tracked_links": """
                    CREATE TABLE tracked_links_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        daily_newsletter_id INTEGER NOT NULL REFERENCES daily_newsletters(id) ON DELETE CASCADE,
                        click_token TEXT NOT NULL UNIQUE,
                        target_url TEXT NOT NULL,
                        story_title TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        UNIQUE(daily_newsletter_id, target_url)
                    )
                """,
                "newsletter_open_events": """
                    CREATE TABLE newsletter_open_events_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        daily_newsletter_id INTEGER NOT NULL REFERENCES daily_newsletters(id) ON DELETE CASCADE,
                        open_token TEXT NOT NULL,
                        opened_at TEXT NOT NULL,
                        user_agent TEXT NOT NULL DEFAULT '',
                        ip_address TEXT NOT NULL DEFAULT ''
                    )
                """,
                "newsletter_click_events": """
                    CREATE TABLE newsletter_click_events_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        daily_newsletter_id INTEGER NOT NULL REFERENCES daily_newsletters(id) ON DELETE CASCADE,
                        tracked_link_id INTEGER NOT NULL REFERENCES tracked_links(id) ON DELETE CASCADE,
                        click_token TEXT NOT NULL,
                        clicked_at TEXT NOT NULL,
                        user_agent TEXT NOT NULL DEFAULT '',
                        ip_address TEXT NOT NULL DEFAULT ''
                    )
                """,
            }

            for table_name, create_sql in dependent_tables.items():
                if not self._table_exists(connection, table_name):
                    continue
                connection.execute(create_sql)
                column_names = [
                    str(row["name"])
                    for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
                ]
                joined_columns = ", ".join(column_names)
                connection.execute(
                    f"""
                    INSERT INTO {table_name}_migrated ({joined_columns})
                    SELECT {joined_columns}
                    FROM {table_name}
                    """
                )

            for table_name in [
                "newsletter_click_events",
                "newsletter_open_events",
                "tracked_links",
                "newsletter_telemetry",
            ]:
                if self._table_exists(connection, table_name):
                    connection.execute(f"DROP TABLE {table_name}")

            connection.execute("DROP TABLE daily_newsletters")
            connection.execute("ALTER TABLE daily_newsletters_migrated RENAME TO daily_newsletters")

            for table_name in [
                "newsletter_telemetry",
                "tracked_links",
                "newsletter_open_events",
                "newsletter_click_events",
            ]:
                migrated_table = f"{table_name}_migrated"
                if self._table_exists(connection, migrated_table):
                    connection.execute(f"ALTER TABLE {migrated_table} RENAME TO {table_name}")
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    def _drop_managed_tables(self, connection: sqlite3.Connection) -> None:
        for table_name in [
            "schema_migrations",
            "article_snapshots",
            "user_source_selections",
            "subscriber_sessions",
            "subscriber_login_tokens",
            "subscriber_profiles",
            "subscribers",
            "newsletter_click_events",
            "newsletter_open_events",
            "tracked_links",
            "newsletter_telemetry",
            "fetched_stories",
            "delivery_runs",
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

            CREATE TABLE IF NOT EXISTS daily_newsletters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                newsletter_date TEXT NOT NULL,
                audience_key TEXT NOT NULL DEFAULT 'default',
                issue_type TEXT NOT NULL DEFAULT 'daily',
                delivery_run_id INTEGER REFERENCES delivery_runs(id) ON DELETE SET NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                html_body TEXT NOT NULL,
                content_json TEXT NOT NULL DEFAULT '{}',
                selected_items_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(newsletter_date, audience_key, issue_type)
            );

            CREATE INDEX IF NOT EXISTS idx_daily_newsletters_date_audience
            ON daily_newsletters(newsletter_date, audience_key, issue_type);

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
                email_sent_at TEXT,
                summary TEXT NOT NULL DEFAULT '',
                raw_payload_json TEXT NOT NULL DEFAULT '{}',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_fetched_stories_source_type ON fetched_stories(source_type);
            CREATE INDEX IF NOT EXISTS idx_fetched_stories_source_name ON fetched_stories(source_name);
            CREATE INDEX IF NOT EXISTS idx_fetched_stories_published_at ON fetched_stories(published_at);
            CREATE INDEX IF NOT EXISTS idx_fetched_stories_email_sent_at ON fetched_stories(email_sent_at);

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

            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_address TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS subscriber_login_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_id INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT,
                request_ip TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_subscriber_login_tokens_subscriber_id
            ON subscriber_login_tokens(subscriber_id);

            CREATE TABLE IF NOT EXISTS subscriber_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_id INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
                session_token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                revoked_at TEXT,
                ip_address TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_subscriber_sessions_subscriber_id
            ON subscriber_sessions(subscriber_id);

            CREATE TABLE IF NOT EXISTS subscriber_profiles (
                subscriber_id INTEGER PRIMARY KEY REFERENCES subscribers(id) ON DELETE CASCADE,
                persona_text TEXT NOT NULL DEFAULT '',
                delivery_format TEXT NOT NULL DEFAULT 'email',
                preferred_sources_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
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

    def get_delivery_run(self, run_id: int) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, status, started_at, finished_at, metadata_json
                FROM delivery_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return self._run_row_to_dict(row)

    def list_recent_ingestion_runs(
        self,
        *,
        source_type: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        conditions: list[str] = []
        params: list[object] = []
        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, int(limit)))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, source_type, status, started_at, finished_at, metadata_json
                FROM ingestion_runs
                {where_clause}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [payload for row in rows if (payload := self._run_row_to_dict(row)) is not None]

    def list_recent_delivery_runs(
        self,
        *,
        limit: int = 30,
    ) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, status, started_at, finished_at, metadata_json
                FROM delivery_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [payload for row in rows if (payload := self._run_row_to_dict(row)) is not None]

    def get_daily_newsletter(
        self,
        newsletter_date: str,
        *,
        audience_key: str = DEFAULT_AUDIENCE_KEY,
        issue_type: str | None = None,
        include_all_audiences: bool = False,
    ) -> dict | None:
        normalized_issue_type = str(issue_type or "").strip().lower()
        if include_all_audiences:
            where_clause = "WHERE newsletter_date = ?"
            order_clause = "ORDER BY CASE WHEN audience_key = ? THEN 0 ELSE 1 END, id DESC"
            params: tuple[str, ...] = (newsletter_date, audience_key)
            if normalized_issue_type:
                where_clause += " AND issue_type = ?"
                params = (newsletter_date, normalized_issue_type, audience_key)
        else:
            where_clause = "WHERE newsletter_date = ? AND audience_key = ?"
            order_clause = ""
            params = (newsletter_date, audience_key)
            if normalized_issue_type:
                where_clause += " AND issue_type = ?"
                params = (newsletter_date, audience_key, normalized_issue_type)
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT
                    id,
                    newsletter_date,
                    audience_key,
                    issue_type,
                    delivery_run_id,
                    subject,
                    body,
                    html_body,
                    content_json,
                    selected_items_json,
                    metadata_json,
                    created_at,
                    updated_at
                FROM daily_newsletters
                {where_clause}
                {order_clause}
                LIMIT 1
                """,
                params,
            ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["content"] = json.loads(str(payload.pop("content_json", "") or "{}"))
        payload["selected_items"] = json.loads(
            str(payload.pop("selected_items_json", "") or "[]")
        )
        payload["metadata"] = json.loads(str(payload.pop("metadata_json", "") or "{}"))
        return payload

    def list_daily_newsletters(
        self,
        *,
        limit: int = 30,
        audience_key: str = DEFAULT_AUDIENCE_KEY,
        include_all_audiences: bool = False,
        one_per_date: bool = False,
    ) -> list[dict]:
        where_clause = "" if include_all_audiences else "WHERE audience_key = ?"
        params: tuple[int] | tuple[str, int]
        params = (limit,) if include_all_audiences else (audience_key, limit)
        if one_per_date:
            if include_all_audiences:
                query = """
                    SELECT
                        id,
                        newsletter_date,
                        audience_key,
                        issue_type,
                        delivery_run_id,
                        subject,
                        body,
                        html_body,
                        content_json,
                        selected_items_json,
                        metadata_json,
                        created_at,
                        updated_at
                    FROM (
                        SELECT
                            id,
                            newsletter_date,
                            audience_key,
                            issue_type,
                            delivery_run_id,
                            subject,
                            body,
                            html_body,
                            content_json,
                            selected_items_json,
                            metadata_json,
                            created_at,
                            updated_at,
                            ROW_NUMBER() OVER (
                                PARTITION BY newsletter_date
                                ORDER BY CASE WHEN audience_key = ? THEN 0 ELSE 1 END, id DESC
                            ) AS row_number
                        FROM daily_newsletters
                    )
                    WHERE row_number = 1
                    ORDER BY newsletter_date DESC, id DESC
                    LIMIT ?
                    """
                params = (audience_key, limit)
            else:
                query = """
                    SELECT
                        id,
                        newsletter_date,
                        audience_key,
                        issue_type,
                        delivery_run_id,
                        subject,
                        body,
                        html_body,
                        content_json,
                        selected_items_json,
                        metadata_json,
                        created_at,
                        updated_at
                    FROM daily_newsletters
                    WHERE audience_key = ?
                    ORDER BY newsletter_date DESC, id DESC
                    LIMIT ?
                    """
        else:
            query = f"""
                SELECT
                    id,
                    newsletter_date,
                    audience_key,
                    issue_type,
                    delivery_run_id,
                    subject,
                    body,
                    html_body,
                    content_json,
                    selected_items_json,
                    metadata_json,
                    created_at,
                    updated_at
                FROM daily_newsletters
                {where_clause}
                ORDER BY newsletter_date DESC, id DESC
                LIMIT ?
                """
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()

        newsletters: list[dict] = []
        for row in rows:
            payload = dict(row)
            payload["content"] = json.loads(str(payload.pop("content_json", "") or "{}"))
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
        audience_key: str = DEFAULT_AUDIENCE_KEY,
        issue_type: str = "daily",
        subject: str,
        body: str,
        html_body: str,
        content: dict | None = None,
        selected_items: list[dict] | None = None,
        metadata: dict | None = None,
        delivery_run_id: int | None = None,
    ) -> int:
        now = utc_now()
        normalized_issue_type = str(issue_type or "daily").strip().lower() or "daily"
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO daily_newsletters (
                    newsletter_date,
                    audience_key,
                    issue_type,
                    delivery_run_id,
                    subject,
                    body,
                    html_body,
                    content_json,
                    selected_items_json,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(newsletter_date, audience_key, issue_type)
                DO UPDATE SET
                    delivery_run_id = excluded.delivery_run_id,
                    subject = excluded.subject,
                    body = excluded.body,
                    html_body = excluded.html_body,
                    content_json = excluded.content_json,
                    selected_items_json = excluded.selected_items_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    newsletter_date,
                    audience_key,
                    normalized_issue_type,
                    delivery_run_id,
                    subject,
                    body,
                    html_body,
                    json.dumps(content or {}, sort_keys=True),
                    json.dumps(selected_items or [], sort_keys=True),
                    json.dumps(metadata or {}, sort_keys=True),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT id
                FROM daily_newsletters
                WHERE newsletter_date = ?
                  AND audience_key = ?
                  AND issue_type = ?
                """,
                (newsletter_date, audience_key, normalized_issue_type),
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

    def upsert_subscriber(self, email_address: str) -> dict:
        normalized_email = str(email_address).strip().lower()
        if not normalized_email:
            raise ValueError("email_address is required")
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO subscribers (email_address, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(email_address)
                DO UPDATE SET updated_at = excluded.updated_at
                """,
                (normalized_email, now, now),
            )
            row = connection.execute(
                """
                SELECT id, email_address, created_at, updated_at, last_login_at
                FROM subscribers
                WHERE email_address = ?
                LIMIT 1
                """,
                (normalized_email,),
            ).fetchone()
        return self._subscriber_row_to_dict(row)

    def get_subscriber_by_email(self, email_address: str) -> dict | None:
        normalized_email = str(email_address).strip().lower()
        if not normalized_email:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, email_address, created_at, updated_at, last_login_at
                FROM subscribers
                WHERE email_address = ?
                LIMIT 1
                """,
                (normalized_email,),
            ).fetchone()
        return self._subscriber_row_to_dict(row)

    def get_subscriber_delivery_profile(self, email_address: str) -> dict | None:
        normalized_email = str(email_address).strip().lower()
        if not normalized_email:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    s.id,
                    s.email_address,
                    s.created_at,
                    s.updated_at,
                    s.last_login_at,
                    p.subscriber_id AS profile_subscriber_id,
                    p.persona_text,
                    p.delivery_format,
                    p.preferred_sources_json
                FROM subscribers s
                LEFT JOIN subscriber_profiles p ON p.subscriber_id = s.id
                WHERE s.email_address = ?
                LIMIT 1
                """,
                (normalized_email,),
            ).fetchone()
        return self._subscriber_delivery_profile_row_to_dict(row)

    def list_subscriber_delivery_profiles(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.id,
                    s.email_address,
                    s.created_at,
                    s.updated_at,
                    s.last_login_at,
                    p.subscriber_id AS profile_subscriber_id,
                    p.persona_text,
                    p.delivery_format,
                    p.preferred_sources_json
                FROM subscribers s
                LEFT JOIN subscriber_profiles p ON p.subscriber_id = s.id
                ORDER BY s.email_address ASC
                """
            ).fetchall()
        return [
            profile
            for profile in (self._subscriber_delivery_profile_row_to_dict(row) for row in rows)
            if profile is not None
        ]

    def create_subscriber_login_token(
        self,
        subscriber_id: int,
        *,
        ttl_minutes: int = 20,
        request_ip: str = "",
        user_agent: str = "",
    ) -> dict:
        raw_token = secrets.token_urlsafe(24)
        now = utc_now()
        expires_at = (datetime.now(UTC) + timedelta(minutes=max(ttl_minutes, 1))).isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO subscriber_login_tokens (
                    subscriber_id,
                    token_hash,
                    created_at,
                    expires_at,
                    request_ip,
                    user_agent
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    subscriber_id,
                    hash_secret_token(raw_token),
                    now,
                    expires_at,
                    str(request_ip or ""),
                    str(user_agent or ""),
                ),
            )
        return {
            "token": raw_token,
            "subscriber_id": int(subscriber_id),
            "created_at": now,
            "expires_at": expires_at,
        }

    def consume_subscriber_login_token(self, raw_token: str) -> dict | None:
        normalized_token = str(raw_token or "").strip()
        if not normalized_token:
            return None
        token_hash = hash_secret_token(normalized_token)
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    t.id AS token_id,
                    s.id,
                    s.email_address,
                    s.created_at,
                    s.updated_at,
                    s.last_login_at
                FROM subscriber_login_tokens t
                JOIN subscribers s ON s.id = t.subscriber_id
                WHERE t.token_hash = ?
                  AND t.consumed_at IS NULL
                  AND t.expires_at >= ?
                LIMIT 1
                """,
                (token_hash, now),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE subscriber_login_tokens
                SET consumed_at = ?
                WHERE id = ?
                """,
                (now, int(row["token_id"])),
            )
        return self._subscriber_row_to_dict(row)

    def create_subscriber_session(
        self,
        subscriber_id: int,
        *,
        ttl_days: int = 30,
        ip_address: str = "",
        user_agent: str = "",
    ) -> dict:
        raw_token = secrets.token_urlsafe(32)
        now = utc_now()
        expires_at = (datetime.now(UTC) + timedelta(days=max(ttl_days, 1))).isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO subscriber_sessions (
                    subscriber_id,
                    session_token_hash,
                    created_at,
                    expires_at,
                    last_seen_at,
                    ip_address,
                    user_agent
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscriber_id,
                    hash_secret_token(raw_token),
                    now,
                    expires_at,
                    now,
                    str(ip_address or ""),
                    str(user_agent or ""),
                ),
            )
            connection.execute(
                """
                UPDATE subscribers
                SET last_login_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, subscriber_id),
            )
        return {
            "token": raw_token,
            "subscriber_id": int(subscriber_id),
            "created_at": now,
            "expires_at": expires_at,
            "last_seen_at": now,
        }

    def get_subscriber_by_session_token(self, raw_token: str) -> dict | None:
        normalized_token = str(raw_token or "").strip()
        if not normalized_token:
            return None
        token_hash = hash_secret_token(normalized_token)
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    s.id,
                    s.email_address,
                    s.created_at,
                    s.updated_at,
                    s.last_login_at,
                    ss.id AS session_id,
                    ss.created_at AS session_created_at,
                    ss.expires_at AS session_expires_at,
                    ss.last_seen_at AS session_last_seen_at
                FROM subscriber_sessions ss
                JOIN subscribers s ON s.id = ss.subscriber_id
                WHERE ss.session_token_hash = ?
                  AND ss.revoked_at IS NULL
                  AND ss.expires_at >= ?
                LIMIT 1
                """,
                (token_hash, now),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE subscriber_sessions
                SET last_seen_at = ?
                WHERE id = ?
                """,
                (now, int(row["session_id"])),
            )
        payload = self._subscriber_row_to_dict(row)
        if payload is not None:
            payload["session"] = {
                "id": int(row["session_id"]),
                "created_at": str(row["session_created_at"] or ""),
                "expires_at": str(row["session_expires_at"] or ""),
                "last_seen_at": now,
            }
        return payload

    def revoke_subscriber_session(self, raw_token: str) -> None:
        normalized_token = str(raw_token or "").strip()
        if not normalized_token:
            return
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE subscriber_sessions
                SET revoked_at = ?
                WHERE session_token_hash = ?
                  AND revoked_at IS NULL
                """,
                (utc_now(), hash_secret_token(normalized_token)),
            )

    def get_subscriber_profile(self, subscriber_id: int) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    subscriber_id,
                    persona_text,
                    delivery_format,
                    preferred_sources_json,
                    created_at,
                    updated_at
                FROM subscriber_profiles
                WHERE subscriber_id = ?
                LIMIT 1
                """,
                (subscriber_id,),
            ).fetchone()
        if row is None:
            return {
                "subscriber_id": int(subscriber_id),
                "profile_exists": False,
                "persona_text": "",
                "delivery_format": DEFAULT_SUBSCRIBER_DELIVERY_FORMAT,
                "preferred_sources": [],
                "created_at": "",
                "updated_at": "",
            }
        return self._subscriber_profile_row_to_dict(row)

    def upsert_subscriber_profile(
        self,
        subscriber_id: int,
        *,
        persona_text: str = "",
        delivery_format: str = DEFAULT_SUBSCRIBER_DELIVERY_FORMAT,
        preferred_sources: list[str] | tuple[str, ...] | None = None,
    ) -> dict:
        normalized_persona = str(persona_text or "").strip()
        normalized_delivery_format = normalize_subscriber_delivery_format(delivery_format)
        normalized_sources: list[str] = []
        seen: set[str] = set()
        for raw_source in preferred_sources or []:
            source_name = str(raw_source or "").strip()
            lowered = source_name.lower()
            if not source_name or lowered in seen:
                continue
            normalized_sources.append(source_name)
            seen.add(lowered)
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO subscriber_profiles (
                    subscriber_id,
                    persona_text,
                    delivery_format,
                    preferred_sources_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(subscriber_id)
                DO UPDATE SET
                    persona_text = excluded.persona_text,
                    delivery_format = excluded.delivery_format,
                    preferred_sources_json = excluded.preferred_sources_json,
                    updated_at = excluded.updated_at
                """,
                (
                    subscriber_id,
                    normalized_persona,
                    normalized_delivery_format,
                    json.dumps(normalized_sources),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT
                    subscriber_id,
                    persona_text,
                    delivery_format,
                    preferred_sources_json,
                    created_at,
                    updated_at
                FROM subscriber_profiles
                WHERE subscriber_id = ?
                LIMIT 1
                """,
                (subscriber_id,),
            ).fetchone()
        return self._subscriber_profile_row_to_dict(row)

    def _run_row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        payload = dict(row)
        metadata_json = str(payload.pop("metadata_json", "") or "{}")
        payload["metadata"] = json.loads(metadata_json)
        return payload

    def _subscriber_row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        payload = dict(row)
        payload.pop("token_id", None)
        payload["id"] = int(payload["id"])
        payload["email_address"] = str(payload.get("email_address", "") or "")
        payload["created_at"] = str(payload.get("created_at", "") or "")
        payload["updated_at"] = str(payload.get("updated_at", "") or "")
        payload["last_login_at"] = str(payload.get("last_login_at", "") or "")
        return payload

    def _subscriber_profile_row_to_dict(self, row: sqlite3.Row | None) -> dict:
        payload = dict(row or {})
        return {
            "subscriber_id": int(payload.get("subscriber_id") or 0),
            "profile_exists": True,
            "persona_text": str(payload.get("persona_text", "") or ""),
            "delivery_format": normalize_subscriber_delivery_format(payload.get("delivery_format")),
            "preferred_sources": json.loads(str(payload.get("preferred_sources_json", "[]") or "[]")),
            "created_at": str(payload.get("created_at", "") or ""),
            "updated_at": str(payload.get("updated_at", "") or ""),
        }

    def _subscriber_delivery_profile_row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        payload = dict(row)
        preferred_sources = json.loads(str(payload.get("preferred_sources_json", "[]") or "[]"))
        return {
            "id": int(payload.get("id") or 0),
            "email_address": str(payload.get("email_address", "") or ""),
            "persona_text": str(payload.get("persona_text", "") or ""),
            "delivery_format": normalize_subscriber_delivery_format(payload.get("delivery_format")),
            "preferred_sources": preferred_sources,
            "profile_exists": payload.get("profile_subscriber_id") is not None,
            "created_at": str(payload.get("created_at", "") or ""),
            "updated_at": str(payload.get("updated_at", "") or ""),
            "last_login_at": str(payload.get("last_login_at", "") or ""),
        }

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

    def _delivery_sent_recipients_sql(self, alias: str) -> str:
        return (
            "COALESCE("
            f"CAST(json_extract({alias}.metadata_json, '$.pipeline_result.sent_recipients') AS INTEGER), "
            f"CAST(json_extract({alias}.metadata_json, '$.sent_recipients') AS INTEGER), "
            "0"
            ")"
        )

    def list_newsletter_analytics(
        self,
        *,
        limit: int = 14,
        audience_key: str = DEFAULT_AUDIENCE_KEY,
        include_all_audiences: bool = False,
    ) -> list[dict]:
        open_visitor_key = self._event_visitor_key_sql("noe")
        click_visitor_key = self._event_visitor_key_sql("nce")
        sent_recipients_sql = self._delivery_sent_recipients_sql("dr")
        with self.connect() as connection:
            if include_all_audiences:
                rows = connection.execute(
                    f"""
                    SELECT
                        MAX(dn.id) AS id,
                        dn.newsletter_date,
                        'all' AS audience_key,
                        COALESCE(
                            MAX(CASE WHEN dn.audience_key = ? THEN dn.subject END),
                            MAX(dn.subject),
                            ''
                        ) AS subject,
                        MAX(dn.created_at) AS created_at,
                        COALESCE(
                            MAX(CASE WHEN dn.audience_key = ? THEN json_array_length(dn.selected_items_json) END),
                            MAX(json_array_length(dn.selected_items_json)),
                            0
                        ) AS selected_items_count,
                        COALESCE(opens.total_opens, 0) AS total_opens,
                        COALESCE(opens.unique_opens, 0) AS unique_opens,
                        COALESCE(clicks.total_clicks, 0) AS total_clicks,
                        COALESCE(clicks.unique_clicks, 0) AS unique_clicks,
                        COALESCE(deliveries.total_stories_delivered, 0) AS total_stories_delivered,
                        (
                            SELECT tl.story_title
                            FROM daily_newsletters dn_top
                            JOIN tracked_links tl ON tl.daily_newsletter_id = dn_top.id
                            JOIN newsletter_click_events nce_top ON nce_top.tracked_link_id = tl.id
                            WHERE dn_top.newsletter_date = dn.newsletter_date
                            GROUP BY tl.story_title, tl.target_url
                            ORDER BY COUNT(nce_top.id) DESC, MIN(tl.id) ASC
                            LIMIT 1
                        ) AS top_story_title,
                        (
                            SELECT tl.target_url
                            FROM daily_newsletters dn_top
                            JOIN tracked_links tl ON tl.daily_newsletter_id = dn_top.id
                            JOIN newsletter_click_events nce_top ON nce_top.tracked_link_id = tl.id
                            WHERE dn_top.newsletter_date = dn.newsletter_date
                            GROUP BY tl.story_title, tl.target_url
                            ORDER BY COUNT(nce_top.id) DESC, MIN(tl.id) ASC
                            LIMIT 1
                        ) AS top_story_url,
                        (
                            SELECT COUNT(nce_top.id)
                            FROM daily_newsletters dn_top
                            JOIN tracked_links tl ON tl.daily_newsletter_id = dn_top.id
                            JOIN newsletter_click_events nce_top ON nce_top.tracked_link_id = tl.id
                            WHERE dn_top.newsletter_date = dn.newsletter_date
                            GROUP BY tl.story_title, tl.target_url
                            ORDER BY COUNT(nce_top.id) DESC, MIN(tl.id) ASC
                            LIMIT 1
                        ) AS top_story_clicks
                    FROM daily_newsletters dn
                    LEFT JOIN (
                        SELECT
                            dn_open.newsletter_date,
                            COUNT(*) AS total_opens,
                            COUNT(DISTINCT {open_visitor_key}) AS unique_opens
                        FROM daily_newsletters dn_open
                        JOIN newsletter_open_events noe ON noe.daily_newsletter_id = dn_open.id
                        GROUP BY dn_open.newsletter_date
                    ) AS opens ON opens.newsletter_date = dn.newsletter_date
                    LEFT JOIN (
                        SELECT
                            dn_click.newsletter_date,
                            COUNT(*) AS total_clicks,
                            COUNT(DISTINCT {click_visitor_key}) AS unique_clicks
                        FROM daily_newsletters dn_click
                        JOIN newsletter_click_events nce ON nce.daily_newsletter_id = dn_click.id
                        GROUP BY dn_click.newsletter_date
                    ) AS clicks ON clicks.newsletter_date = dn.newsletter_date
                    LEFT JOIN (
                        SELECT
                            dn_delivery.newsletter_date,
                            SUM(
                                json_array_length(dn_delivery.selected_items_json) * {sent_recipients_sql}
                            ) AS total_stories_delivered
                        FROM daily_newsletters dn_delivery
                        LEFT JOIN delivery_runs dr ON dr.id = dn_delivery.delivery_run_id
                        GROUP BY dn_delivery.newsletter_date
                    ) AS deliveries ON deliveries.newsletter_date = dn.newsletter_date
                    GROUP BY dn.newsletter_date
                    ORDER BY dn.newsletter_date DESC, MAX(dn.id) DESC
                    LIMIT ?
                    """,
                    (audience_key, audience_key, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"""
                    SELECT
                        dn.id,
                        dn.newsletter_date,
                        dn.audience_key,
                        dn.subject,
                        dn.created_at,
                        dn.selected_items_json,
                        COALESCE(opens.total_opens, 0) AS total_opens,
                        COALESCE(opens.unique_opens, 0) AS unique_opens,
                        COALESCE(clicks.total_clicks, 0) AS total_clicks,
                        COALESCE(clicks.unique_clicks, 0) AS unique_clicks,
                        COALESCE(deliveries.total_stories_delivered, 0) AS total_stories_delivered,
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
                    LEFT JOIN (
                        SELECT
                            dn_delivery.id AS daily_newsletter_id,
                            json_array_length(dn_delivery.selected_items_json) * {sent_recipients_sql}
                                AS total_stories_delivered
                        FROM daily_newsletters dn_delivery
                        LEFT JOIN delivery_runs dr ON dr.id = dn_delivery.delivery_run_id
                    ) AS deliveries ON deliveries.daily_newsletter_id = dn.id
                    WHERE dn.audience_key = ?
                    ORDER BY dn.newsletter_date DESC, dn.id DESC
                    LIMIT ?
                    """,
                    (audience_key, limit),
                ).fetchall()

        analytics: list[dict] = []
        for row in rows:
            payload = dict(row)
            if "selected_items_count" in payload:
                payload["selected_items_count"] = int(payload.get("selected_items_count", 0) or 0)
            else:
                selected_items = json.loads(str(payload.pop("selected_items_json", "") or "[]"))
                payload["selected_items_count"] = len(selected_items)
            payload["total_stories_delivered"] = int(payload.get("total_stories_delivered", 0) or 0)
            total_stories_delivered = int(payload["total_stories_delivered"])
            unique_clicks = int(payload["unique_clicks"])
            payload["click_through_rate"] = (
                round((unique_clicks / total_stories_delivered) * 100, 1)
                if total_stories_delivered
                else None
            )
            analytics.append(payload)
        return analytics

    def get_newsletter_aggregate_stats(
        self,
        *,
        trailing_days: tuple[int, ...] = (7, 30),
        audience_key: str = DEFAULT_AUDIENCE_KEY,
        include_all_audiences: bool = False,
    ) -> list[dict]:
        open_visitor_key = self._event_visitor_key_sql("noe")
        click_visitor_key = self._event_visitor_key_sql("nce")
        sent_recipients_sql = self._delivery_sent_recipients_sql("dr")
        today = datetime.now(UTC).date()
        windows: list[dict] = []

        with self.connect() as connection:
            for days in trailing_days:
                since_date = (today - timedelta(days=max(days - 1, 0))).isoformat()
                scoped_newsletters_where = (
                    "WHERE newsletter_date >= ?"
                    if include_all_audiences
                    else "WHERE newsletter_date >= ? AND audience_key = ?"
                )
                params: tuple[str] | tuple[str, str]
                params = (since_date,) if include_all_audiences else (since_date, audience_key)
                row = connection.execute(
                    f"""
                    WITH scoped_newsletters AS (
                        SELECT
                            id,
                            newsletter_date,
                            delivery_run_id,
                            json_array_length(selected_items_json) AS selected_items_count
                        FROM daily_newsletters
                        {scoped_newsletters_where}
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
                    ),
                    delivery_stats AS (
                        SELECT
                            sn.id AS daily_newsletter_id,
                            sn.selected_items_count * {sent_recipients_sql} AS total_stories_delivered
                        FROM scoped_newsletters sn
                        LEFT JOIN delivery_runs dr ON dr.id = sn.delivery_run_id
                    )
                    SELECT
                        (SELECT COUNT(*) FROM scoped_newsletters) AS newsletters,
                        COALESCE((SELECT SUM(total_opens) FROM open_stats), 0) AS total_opens,
                        COALESCE((SELECT SUM(unique_opens) FROM open_stats), 0) AS unique_opens,
                        COALESCE((SELECT SUM(total_clicks) FROM click_stats), 0) AS total_clicks,
                        COALESCE((SELECT SUM(unique_clicks) FROM click_stats), 0) AS unique_clicks,
                        COALESCE(
                            (SELECT SUM(total_stories_delivered) FROM delivery_stats),
                            0
                        ) AS total_stories_delivered
                    """,
                    params,
                ).fetchone()
                payload = dict(row or {})
                total_stories_delivered = int(payload.get("total_stories_delivered", 0) or 0)
                unique_clicks = int(payload.get("unique_clicks", 0) or 0)
                payload["days"] = days
                payload["since_date"] = since_date
                payload["click_through_rate"] = (
                    round((unique_clicks / total_stories_delivered) * 100, 1)
                    if total_stories_delivered
                    else None
                )
                windows.append(payload)
        return windows

    def list_top_clicked_stories(
        self,
        *,
        trailing_days: int = 30,
        limit: int = 10,
        audience_key: str = DEFAULT_AUDIENCE_KEY,
        include_all_audiences: bool = False,
    ) -> list[dict]:
        click_visitor_key = self._event_visitor_key_sql("nce")
        since_date = (datetime.now(UTC).date() - timedelta(days=max(trailing_days - 1, 0))).isoformat()
        audience_filter = "" if include_all_audiences else "AND dn.audience_key = ?"
        params: tuple[str, int] | tuple[str, str, int]
        params = (since_date, limit) if include_all_audiences else (since_date, audience_key, limit)
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
                  {audience_filter}
                GROUP BY tl.story_title, tl.target_url
                ORDER BY total_clicks DESC, unique_clicks DESC, last_newsletter_date DESC
                LIMIT ?
                """,
                params,
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
        email_sent_at = str(story.get("email_sent_at", "")).strip()
        if not email_sent_at and source_type == "gmail":
            email_sent_at = normalize_email_datetime(str(story.get("date", "")).strip())

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
                    email_sent_at,
                    summary,
                    raw_payload_json,
                    first_seen_at,
                    last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    email_sent_at = excluded.email_sent_at,
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
                    email_sent_at,
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

    def get_article_text_for_story(self, story_id: int) -> str:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT article_text
                FROM article_snapshots
                WHERE story_id = ?
                LIMIT 1
                """,
                (story_id,),
            ).fetchone()
        return str(row["article_text"]) if row is not None else ""

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
                "enabled": (
                    is_default_enabled_source_name(str(row["source_name"]))
                    if row["enabled"] is None
                    else bool(row["enabled"])
                ),
            }
            for row in rows
        ]

    def list_enabled_sources(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
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
                "source_type": row["source_type"],
                "source_name": row["source_name"],
                "enabled": True if row["enabled"] is None else bool(row["enabled"]),
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
            if source_type == "gmail":
                conditions.append("COALESCE(NULLIF(email_sent_at, ''), published_at) >= ?")
            else:
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
                fs.email_sent_at,
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
            ORDER BY
                CASE
                    WHEN fs.source_type = 'gmail' THEN COALESCE(NULLIF(fs.email_sent_at, ''), fs.published_at, fs.first_seen_at)
                    ELSE COALESCE(fs.published_at, fs.first_seen_at)
                END DESC,
                fs.id DESC
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
