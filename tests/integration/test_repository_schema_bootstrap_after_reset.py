from __future__ import annotations

import json
import sqlite3

import pytest

from curator.repository import SQLiteRepository, SchemaResetRequiredError
from tests.helpers import temp_db_path


def test_repository_schema_bootstrap_after_reset(tmp_path):
    db_path = temp_db_path(tmp_path)
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
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
            source_id INTEGER NOT NULL,
            ingestion_run_id INTEGER,
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

        CREATE TABLE article_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            story_id INTEGER NOT NULL UNIQUE,
            article_text TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE user_source_selections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );

        INSERT INTO schema_migrations (version, applied_at) VALUES (1, '2026-03-20T00:00:00+00:00');
        INSERT INTO sources (source_type, source_name, created_at, updated_at)
        VALUES ('gmail', 'Old Source', '2026-03-20T00:00:00+00:00', '2026-03-20T00:00:00+00:00');
        """
    )
    connection.commit()
    connection.close()

    repository = SQLiteRepository(db_path)
    with pytest.raises(SchemaResetRequiredError) as excinfo:
        repository.initialize()

    assert "were not reset automatically" in str(excinfo.value)

    with sqlite3.connect(db_path) as connection:
        source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        migration_count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert source_count == 1
    assert migration_count == 1

    repository.initialize(allow_schema_reset=True)

    counts = repository.get_table_counts()
    assert counts["schema_migrations"] == 0
    assert counts["sources"] == 0

    with repository.connect() as connection:
        snapshot_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(article_snapshots)").fetchall()
        }
        table_row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()

    assert table_row is None
    assert {
        "paywall_detected",
        "paywall_reason",
        "summary_raw",
        "summary_headline",
        "summary_body",
        "summary_model",
        "summarized_at",
    }.issubset(snapshot_columns)


def test_repository_migration_backfills_gmail_email_sent_at(tmp_path):
    db_path = temp_db_path(tmp_path)
    email_header = "Mon, 23 Mar 2026 12:34:56 +0000"
    with sqlite3.connect(db_path) as connection:
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

            CREATE TABLE fetched_stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                story_key TEXT NOT NULL UNIQUE,
                source_id INTEGER NOT NULL,
                ingestion_run_id INTEGER,
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
            """
        )
        connection.execute(
            """
            INSERT INTO sources (id, source_type, source_name, created_at, updated_at)
            VALUES (1, 'gmail', 'Macro Letter', '2026-03-23T00:00:00+00:00', '2026-03-23T00:00:00+00:00')
            """
        )
        connection.execute(
            """
            INSERT INTO fetched_stories (
                story_key,
                source_id,
                source_type,
                source_name,
                subject,
                url,
                canonical_url,
                published_at,
                raw_payload_json,
                first_seen_at,
                last_seen_at
            )
            VALUES (?, 1, 'gmail', 'Macro Letter', 'Old byline', ?, ?, ?, ?, ?, ?)
            """,
            (
                "gmail-story",
                "https://example.com/story",
                "https://example.com/story",
                "2026-03-21T12:15:00+00:00",
                json.dumps({"date": email_header}),
                "2026-03-23T12:35:00+00:00",
                "2026-03-23T12:35:00+00:00",
            ),
        )

    repository = SQLiteRepository(db_path)
    repository.initialize()

    stories = repository.list_stories(
        source_type="gmail",
        published_after="2026-03-23T00:00:00+00:00",
    )

    assert len(stories) == 1
    assert stories[0]["published_at"] == "2026-03-21T12:15:00+00:00"
    assert stories[0]["email_sent_at"] == "2026-03-23T12:34:56+00:00"
