from __future__ import annotations

import importlib

from curator.jobs import get_repository_from_config, run_fetch_sources_job
from tests.fakes import FakeArticleFetcher, FakeOpenAI, FakeSourceFetcher
from tests.helpers import write_temp_config


def test_paywalled_stories_are_excluded_from_digest(monkeypatch, tmp_path):
    main = importlib.import_module("main")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3"), "ttl_days": 7},
            "development": {"fake_inference": True},
            "email": {
                "digest_recipients": ["paywall@example.com"],
                "digest_subject": "Paywall Digest",
            },
            "additional_sources": {"enabled": True, "hours": 48},
            "limits": {
                "select_top_stories": 2,
                "final_top_stories": 2,
                "source_quotas": {"gmail": 0, "additional_source": 2},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    source_fetcher = FakeSourceFetcher(
        [
            {
                "subject": "[markets] Rates reset",
                "from": "Macro Wire",
                "source_name": "Macro Wire",
                "source_type": "additional_source",
                "date": "2026-03-21T07:30:00+00:00",
                "url": "https://example.com/markets/rates-reset",
                "anchor_text": "Rates reset changes software valuations",
                "context": "Rates reset context",
                "category": "Markets / stocks / macro / economy",
            },
            {
                "subject": "[media] Subscriber-only analysis",
                "from": "Locked Wire",
                "source_name": "Locked Wire",
                "source_type": "additional_source",
                "date": "2026-03-21T06:00:00+00:00",
                "url": "https://example.com/media/subscriber-analysis",
                "anchor_text": "Subscriber-only analysis",
                "context": "Subscriber analysis context",
                "category": "Tech blogs",
            },
            {
                "subject": "[markets] JS blocked placeholder",
                "from": "Blocked Wire",
                "source_name": "Blocked Wire",
                "source_type": "additional_source",
                "date": "2026-03-21T05:00:00+00:00",
                "url": "https://example.com/markets/js-blocked",
                "anchor_text": "Markets deep dive",
                "context": "Blocked placeholder context",
                "category": "Markets / stocks / macro / economy",
            },
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            "https://example.com/markets/rates-reset": (
                "Rates reset changes software valuations and reprices growth names."
            ),
            "https://example.com/media/subscriber-analysis": (
                "Subscribe to continue reading. Already a subscriber? Sign in to continue reading."
            ),
            "https://example.com/markets/js-blocked": (
                "Site content blocked due to JavaScript being disabled. "
                "Please enable JavaScript to continue reading this page."
            ),
        }
    )

    fetch_result = run_fetch_sources_job(
        config,
        source_fetcher=source_fetcher,
        article_fetcher=article_fetcher,
    )
    repository = get_repository_from_config(config)
    stories = repository.list_stories(source_type="additional_source")
    visible_stories = repository.list_stories(source_type="additional_source", include_paywalled=False)

    monkeypatch.setattr(main, "OpenAI", FakeOpenAI)
    preview_result = main.preview_job(config)

    assert fetch_result["status"] == "completed"
    assert fetch_result["paywall_stories"] == 2
    assert len(stories) == 1
    assert len(visible_stories) == 1
    assert visible_stories[0]["source_name"] == "Macro Wire"
    assert all(story["source_name"] != "Locked Wire" for story in stories)
    assert all(story["source_name"] != "Blocked Wire" for story in stories)

    assert preview_result["status"] == "completed"
    assert preview_result["accepted_items"] == 1
    assert preview_result["preview"] is not None
    assert "Rates reset changes software valuations" in preview_result["preview"]["body"]
    assert "Subscriber-only analysis" not in preview_result["preview"]["body"]
    assert "Markets deep dive" not in preview_result["preview"]["body"]
