from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from curator.config import DEFAULT_CONFIG, load_config
from curator.jobs import run_fetch_gmail_job
from curator.sources import collect_additional_source_links
from tests.fakes import FakeArticleFetcher, FakeGmailService, make_gmail_message
from tests.helpers import write_temp_config


def test_default_gmail_discovery_budget_fetches_more_candidates(tmp_path):
    html_body = "<html><body>" + "".join(
        (
            f'<p>Context {index} <a href="https://example.com/story-{index:02d}">'
            f"Story {index:02d}</a></p>"
        )
        for index in range(1, 26)
    ) + "</body></html>"

    service = FakeGmailService(
        messages=[
            make_gmail_message(
                message_id="msg-1",
                subject="Daily Macro Notes",
                from_header="Macro Letter <macro@example.com>",
                date_header="Tue, 24 Mar 2026 14:00:00 +0000",
                html_body=html_body,
            )
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            f"https://example.com/story-{index:02d}": (
                f"Story {index:02d} article text with enough detail to summarize deterministically."
            )
            for index in range(1, 26)
        }
    )

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "additional_sources": {"enabled": False},
            "limits": {
                "max_links_per_email": 25,
                "max_ingest_summaries": 10,
            },
        },
    )
    config = load_config(str(config_path))

    result = run_fetch_gmail_job(config, service, article_fetcher=article_fetcher)

    assert DEFAULT_CONFIG["limits"]["max_gmail_fetch_after_score"] == 25
    assert DEFAULT_CONFIG["limits"]["max_ingest_summaries"] == 25
    assert config["limits"]["max_gmail_fetch_after_score"] == 25
    assert result["status"] == "completed"
    assert result["stories_seen"] == 25
    assert result["stories_selected_for_fetch"] == 25
    assert len(article_fetcher.calls) == 25
    assert config["limits"]["final_top_stories"] == 15
    assert config["limits"]["source_quotas"] == {"gmail": 10, "additional_source": 5}


def test_additional_source_discovery_requests_thirty_candidates_by_default(monkeypatch, tmp_path):
    captured_kwargs: list[dict] = []
    script_path = tmp_path / "fake_digest.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    def fake_builder(**kwargs):
        captured_kwargs.append(dict(kwargs))
        return {"stories": [], "failures": []}

    monkeypatch.setattr("curator.sources._load_additional_source_builder", lambda _path: fake_builder)

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "additional_sources": {
                "enabled": True,
                "script_path": str(script_path),
            }
        },
    )
    config = load_config(str(config_path))

    links = collect_additional_source_links(config, base_dir=Path(tmp_path))

    assert links == []
    assert DEFAULT_CONFIG["additional_sources"]["max_total"] == 30
    assert config["additional_sources"]["max_total"] == 30
    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["feeds_file"] is None
    assert captured_kwargs[0]["hours"] == 24
    assert captured_kwargs[0]["top_per_category"] == 5
    assert captured_kwargs[0]["max_total"] == 30
    assert captured_kwargs[0]["allowed_source_names"] == []
    assert captured_kwargs[0]["total_timeout_seconds"] == 300
    assert callable(captured_kwargs[0]["event_logger"])
    assert config["limits"]["final_top_stories"] == 15
    assert config["limits"]["source_quotas"] == {"gmail": 10, "additional_source": 5}


def test_additional_source_collection_filters_feeds_to_allowed_sources(monkeypatch, tmp_path):
    captured_kwargs: list[dict] = []
    script_path = tmp_path / "fake_digest.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    def fake_builder(**kwargs):
        captured_kwargs.append(dict(kwargs))
        return {"stories": [], "failures": []}

    monkeypatch.setattr("curator.sources._load_additional_source_builder", lambda _path: fake_builder)

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "additional_sources": {
                "enabled": True,
                "script_path": str(script_path),
            }
        },
    )
    config = load_config(str(config_path))

    links = collect_additional_source_links(
        config,
        base_dir=Path(tmp_path),
        allowed_source_names=["OpenAI News", " openai news ", "Google AI Blog"],
    )

    assert links == []
    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["allowed_source_names"] == [
        "google ai blog",
        "openai news",
    ]


def test_additional_source_builder_failure_returns_no_links_and_emits_debug_event(monkeypatch, tmp_path):
    emitted_events: list[tuple[str, dict]] = []
    script_path = tmp_path / "fake_digest.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    def fake_builder(**kwargs):
        raise TimeoutError("feed stalled")

    monkeypatch.setattr("curator.sources._load_additional_source_builder", lambda _path: fake_builder)
    monkeypatch.setattr(
        "curator.sources.emit_event",
        lambda event, /, **payload: emitted_events.append((event, payload)),
    )

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "additional_sources": {
                "enabled": True,
                "script_path": str(script_path),
                "command_timeout_seconds": 42,
            }
        },
    )
    config = load_config(str(config_path))

    links = collect_additional_source_links(config, base_dir=Path(tmp_path))

    assert links == []
    assert emitted_events == [
        (
            "additional_source_collection_started",
            {
                "script_path": str(script_path),
                "timeout_seconds": 42,
                "hours": 24,
                "top_per_category": 5,
                "max_total": 30,
                "max_feed_workers": 5,
                "custom_feeds": False,
            },
        ),
        (
            "additional_source_collection_failed",
            {
                "script_path": str(script_path),
                "error": "feed stalled",
                "error_type": "TimeoutError",
            },
        ),
    ]


def test_additional_source_builder_accepts_dataclass_story_output(monkeypatch, tmp_path):
    @dataclass
    class Story:
        category: str
        source: str
        title: str
        url: str
        published_at: datetime
        summary: str

    script_path = tmp_path / "fake_digest.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    def fake_builder(**kwargs):
        return {
            "stories": [
                Story(
                    category="ai",
                    source="OpenAI News",
                    title="The next phase of enterprise AI",
                    url="https://openai.com/index/next-phase-of-enterprise-ai",
                    published_at=datetime(2026, 4, 11, 12, 0, 0, tzinfo=UTC),
                    summary="OpenAI describes the next phase of enterprise AI adoption.",
                )
            ],
            "failures": [],
        }

    monkeypatch.setattr("curator.sources._load_additional_source_builder", lambda _path: fake_builder)

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "additional_sources": {
                "enabled": True,
                "script_path": str(script_path),
            }
        },
    )
    config = load_config(str(config_path))

    links = collect_additional_source_links(config, base_dir=Path(tmp_path))

    assert links == [
        {
            "subject": "[ai] The next phase of enterprise AI",
            "from": "OpenAI News",
            "source_name": "OpenAI News",
            "source_type": "additional_source",
            "date": "2026-04-11T12:00:00+00:00",
            "published_at": "2026-04-11T12:00:00+00:00",
            "url": "https://openai.com/index/next-phase-of-enterprise-ai",
            "anchor_text": "The next phase of enterprise AI",
            "context": "OpenAI describes the next phase of enterprise AI adoption.",
        }
    ]
