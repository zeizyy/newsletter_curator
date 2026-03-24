from __future__ import annotations

import importlib
import json

from curator.jobs import get_repository_from_config, run_fetch_sources_job
from tests.fakes import FakeArticleFetcher, FakeSourceFetcher
from tests.helpers import write_temp_config


def test_fetch_sources_job_writes_repository(monkeypatch, tmp_path, capsys):
    fetch_sources = importlib.import_module("fetch_sources")
    original_load_config = fetch_sources.load_config

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "additional_sources": {"enabled": True},
            "development": {"fake_inference": True},
            "limits": {"max_article_chars": 120},
        },
    )
    fake_source_fetcher = FakeSourceFetcher(
        [
            {
                "subject": "[markets] Rates reset",
                "from": "Macro Wire",
                "source_name": "Macro Wire",
                "source_type": "additional_source",
                "date": "2026-03-21T07:30:00+00:00",
                "url": "https://example.com/markets/rates-reset?utm_source=newsletter",
                "anchor_text": "Rates reset changes software valuations",
                "context": "First context for rates reset",
                "category": "Markets / stocks / macro / economy",
                "summary": "Rates reset summary",
            },
            {
                "subject": "[ai] Open model pricing changed",
                "from": "AI Wire",
                "source_name": "AI Wire",
                "source_type": "additional_source",
                "date": "2026-03-21T06:00:00+00:00",
                "url": "https://example.com/ai/model-pricing",
                "anchor_text": "Open model pricing changed",
                "context": "AI pricing context",
                "category": "AI & ML industry developments",
                "summary": "Pricing summary",
            },
        ]
    )
    fake_article_fetcher = FakeArticleFetcher(
        {
            "https://example.com/markets/rates-reset?utm_source=newsletter": (
                "Rates reset changes software valuations and reprices growth."
            ),
            "https://example.com/ai/model-pricing": (
                "Open model pricing changed and pushes buyers to recalculate inference budgets."
            ),
        }
    )

    monkeypatch.setattr(fetch_sources, "load_config", lambda: original_load_config(str(config_path)))
    monkeypatch.setattr("curator.jobs.collect_additional_source_links", fake_source_fetcher)
    monkeypatch.setattr("curator.jobs.fetch_article_details", fake_article_fetcher)

    config = original_load_config(str(config_path))
    first_result = run_fetch_sources_job(config)
    second_result = run_fetch_sources_job(config)

    repository = get_repository_from_config(config)
    counts = repository.get_table_counts()
    stories = repository.list_stories(source_type="additional_source")

    assert first_result["status"] == "completed"
    assert second_result["status"] == "completed"
    assert fake_source_fetcher.calls == 2
    assert counts["ingestion_runs"] == 2
    assert counts["fetched_stories"] == 2
    assert counts["article_snapshots"] == 2
    assert len(stories) == 2
    assert stories[0]["source_name"] == "Macro Wire"
    assert stories[1]["source_name"] == "AI Wire"
    assert stories[0]["article_text"]
    assert stories[1]["article_text"]
    assert stories[0]["summary_headline"]
    assert stories[0]["summary_body"]
    assert stories[1]["summary_headline"]
    assert stories[1]["summary_body"]
    assert first_result["usage_by_model"][config["openai"]["summary_model"]]["total"] > 0

    fetch_sources.main()
    captured = capsys.readouterr()
    json_start = captured.out.rfind('{\n  "')
    assert json_start != -1
    cli_result = json.loads(captured.out[json_start:])
    assert cli_result["status"] == "completed"
