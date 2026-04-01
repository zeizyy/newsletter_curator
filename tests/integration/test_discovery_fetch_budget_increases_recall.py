from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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
        for index in range(1, 21)
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
            for index in range(1, 21)
        }
    )

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "additional_sources": {"enabled": False},
            "limits": {
                "max_links_per_email": 20,
                "max_ingest_summaries": 10,
            },
        },
    )
    config = load_config(str(config_path))

    result = run_fetch_gmail_job(config, service, article_fetcher=article_fetcher)

    assert DEFAULT_CONFIG["limits"]["max_gmail_fetch_after_score"] == 20
    assert config["limits"]["max_gmail_fetch_after_score"] == 20
    assert result["status"] == "completed"
    assert result["stories_seen"] == 20
    assert result["stories_selected_for_fetch"] == 20
    assert len(article_fetcher.calls) == 20
    assert config["limits"]["final_top_stories"] == 15
    assert config["limits"]["source_quotas"] == {"gmail": 10, "additional_source": 5}


def test_additional_source_discovery_requests_thirty_candidates_by_default(monkeypatch, tmp_path):
    captured_commands: list[list[str]] = []
    script_path = tmp_path / "fake_digest.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    def fake_run(command: list[str], capture_output: bool, text: bool, check: bool):
        captured_commands.append(list(command))
        return SimpleNamespace(returncode=0, stdout=json.dumps([]), stderr="")

    monkeypatch.setattr("curator.sources.subprocess.run", fake_run)

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
    assert captured_commands == [
        [
            "python3",
            str(script_path),
            "--output",
            "json",
            "--hours",
            "24",
            "--top-per-category",
            "5",
            "--max-total",
            "30",
        ]
    ]
    assert config["limits"]["final_top_stories"] == 15
    assert config["limits"]["source_quotas"] == {"gmail": 10, "additional_source": 5}
