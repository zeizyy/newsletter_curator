from __future__ import annotations

import sqlite3

from curator.repository import SQLiteRepository
from tests.helpers import temp_db_path


def test_daily_newsletter_audience_key_migration_preserves_telemetry(tmp_path):
    db_path = temp_db_path(tmp_path)
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE delivery_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE daily_newsletters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            newsletter_date TEXT NOT NULL UNIQUE,
            delivery_run_id INTEGER REFERENCES delivery_runs(id) ON DELETE SET NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            html_body TEXT NOT NULL,
            content_json TEXT NOT NULL DEFAULT '{}',
            selected_items_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE newsletter_telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            daily_newsletter_id INTEGER NOT NULL UNIQUE REFERENCES daily_newsletters(id) ON DELETE CASCADE,
            open_token TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE tracked_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            daily_newsletter_id INTEGER NOT NULL REFERENCES daily_newsletters(id) ON DELETE CASCADE,
            click_token TEXT NOT NULL UNIQUE,
            target_url TEXT NOT NULL,
            story_title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(daily_newsletter_id, target_url)
        );

        INSERT INTO daily_newsletters (
            id,
            newsletter_date,
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
        VALUES (
            7,
            '2026-03-24',
            NULL,
            'Legacy Digest',
            'Legacy body',
            '<html><body>Legacy body</body></html>',
            '{}',
            '[]',
            '{}',
            '2026-03-24T18:00:00+00:00',
            '2026-03-24T18:00:00+00:00'
        );

        INSERT INTO newsletter_telemetry (daily_newsletter_id, open_token, created_at)
        VALUES (7, 'legacy-open-token', '2026-03-24T18:00:00+00:00');

        INSERT INTO tracked_links (
            daily_newsletter_id,
            click_token,
            target_url,
            story_title,
            created_at
        )
        VALUES (
            7,
            'legacy-click-token',
            'https://example.com/legacy',
            'Legacy Story',
            '2026-03-24T18:00:00+00:00'
        );
        """
    )
    connection.commit()
    connection.close()

    repository = SQLiteRepository(db_path)
    repository.initialize()

    migrated = repository.get_daily_newsletter("2026-03-24")
    assert migrated is not None
    assert migrated["id"] == 7
    assert migrated["audience_key"] == "default"
    assert migrated["subject"] == "Legacy Digest"

    with repository.connect() as connection:
        telemetry_count = connection.execute(
            "SELECT COUNT(*) FROM newsletter_telemetry WHERE daily_newsletter_id = 7"
        ).fetchone()[0]
        tracked_link_count = connection.execute(
            "SELECT COUNT(*) FROM tracked_links WHERE daily_newsletter_id = 7"
        ).fetchone()[0]

    assert telemetry_count == 1
    assert tracked_link_count == 1

    personalized_id = repository.upsert_daily_newsletter(
        newsletter_date="2026-03-24",
        audience_key="profile-123",
        subject="Personalized Digest",
        body="Personalized body",
        html_body="<html><body>Personalized body</body></html>",
        selected_items=[{"title": "Personalized Story", "url": "https://example.com/personalized"}],
    )

    assert personalized_id != 7
    assert repository.get_daily_newsletter("2026-03-24", audience_key="profile-123") is not None
