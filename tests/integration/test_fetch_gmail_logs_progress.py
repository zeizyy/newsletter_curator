from __future__ import annotations

import json

from curator.config import load_config
from curator.jobs import run_fetch_gmail_job
from tests.fakes import FakeArticleFetcher, FakeGmailService, make_gmail_message
from tests.helpers import write_temp_config


def test_fetch_gmail_logs_progress(tmp_path, capsys):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "limits": {"max_article_chars": 120, "max_fetch_workers": 2},
        },
    )
    service = FakeGmailService(
        messages=[
            make_gmail_message(
                message_id="msg-1",
                subject="AI Wire",
                from_header="AI Wire <news@example.com>",
                date_header="Mon, 23 Mar 2026 14:00:00 +0000",
                html_body=(
                    '<html><body><p><a href="https://example.com/story-1">'
                    "Story one</a></p></body></html>"
                ),
            )
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {"https://example.com/story-1": "Story article text with enough detail to summarize."}
    )

    config = load_config(str(config_path))
    result = run_fetch_gmail_job(config, service, article_fetcher=article_fetcher)

    captured = capsys.readouterr()
    progress_events = [
        json.loads(line)
        for line in captured.out.splitlines()
        if '"event": "ingest_progress"' in line
    ]

    assert result["status"] == "completed"
    stages = [event["stage"] for event in progress_events]
    assert stages == [
        "stories_collected",
        "article_fetch_started",
        "article_fetch_finished",
        "article_fetch_progress",
        "article_fetch_complete",
        "prepared_candidates",
        "scoring_complete",
        "summaries_complete",
        "persist_complete",
    ]
    started = next(event for event in progress_events if event["stage"] == "article_fetch_started")
    finished = next(event for event in progress_events if event["stage"] == "article_fetch_finished")
    assert started["url"] == "https://example.com/story-1"
    assert finished["url"] == "https://example.com/story-1"
