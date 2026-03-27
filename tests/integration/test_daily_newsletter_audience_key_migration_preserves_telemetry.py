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

        CREATE TABLE newsletter_open_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            daily_newsletter_id INTEGER NOT NULL REFERENCES daily_newsletters(id) ON DELETE CASCADE,
            open_token TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            user_agent TEXT NOT NULL DEFAULT '',
            ip_address TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE newsletter_click_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            daily_newsletter_id INTEGER NOT NULL REFERENCES daily_newsletters(id) ON DELETE CASCADE,
            tracked_link_id INTEGER NOT NULL REFERENCES tracked_links(id) ON DELETE CASCADE,
            click_token TEXT NOT NULL,
            clicked_at TEXT NOT NULL,
            user_agent TEXT NOT NULL DEFAULT '',
            ip_address TEXT NOT NULL DEFAULT ''
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
        ) VALUES (
            11,
            '2026-03-24',
            NULL,
            'Legacy Digest',
            'Legacy body',
            '<div>Legacy body</div>',
            '{}',
            '[]',
            '{}',
            '2026-03-24T17:00:00+00:00',
            '2026-03-24T17:00:00+00:00'
        );

        INSERT INTO newsletter_telemetry (id, daily_newsletter_id, open_token, created_at)
        VALUES (21, 11, 'open-token-123', '2026-03-24T17:05:00+00:00');

        INSERT INTO tracked_links (id, daily_newsletter_id, click_token, target_url, story_title, created_at)
        VALUES (31, 11, 'click-token-123', 'https://example.com/story', 'Legacy Story', '2026-03-24T17:06:00+00:00');
        """
    )
    connection.commit()
    connection.close()

    repository = SQLiteRepository(db_path)
    repository.initialize()

    newsletter = repository.get_daily_newsletter("2026-03-24")
    newsletters = repository.list_daily_newsletters(limit=10, include_all_audiences=True)

    assert newsletter is not None
    assert newsletter["id"] == 11
    assert newsletter["audience_key"] == "default"
    assert newsletters[0]["id"] == 11
    assert newsletters[0]["audience_key"] == "default"

    open_event = repository.record_newsletter_open(
        "open-token-123",
        user_agent="test-agent",
        ip_address="1.1.1.1",
    )
    click_event = repository.record_newsletter_click(
        "click-token-123",
        user_agent="test-agent",
        ip_address="1.1.1.1",
    )

    assert open_event["daily_newsletter_id"] == 11
    assert click_event["daily_newsletter_id"] == 11

    counts = repository.get_table_counts()
    assert counts["newsletter_telemetry"] == 1
    assert counts["tracked_links"] == 1
    assert counts["newsletter_open_events"] == 1
    assert counts["newsletter_click_events"] == 1
