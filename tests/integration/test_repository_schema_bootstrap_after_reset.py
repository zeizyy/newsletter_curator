from __future__ import annotations

import sqlite3

from curator.repository import SQLiteRepository
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
    repository.initialize()

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
        "servability_status",
        "detector_version",
        "classifier_signals_json",
        "summary_raw",
        "summary_headline",
        "summary_body",
        "summary_model",
        "summarized_at",
    }.issubset(snapshot_columns)
