from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

from curator.jobs import get_repository_from_config, run_fetch_sources_job
from tests.fakes import FakeArticleFetcher, FakeSourceFetcher
from tests.helpers import write_temp_config


class RankingOnlyOpenAI:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, *, model: str, messages: list[dict]):
        user_message = next(message["content"] for message in messages if message["role"] == "user")
        if "Select the top stories." not in user_message:
            raise AssertionError("Preview should not call the summary model when ingest summaries exist.")
        content = json.dumps(
            [
                {
                    "index": 1,
                    "category": "Markets / stocks / macro / economy",
                    "score": 9.5,
                    "rationale": "Ranking-only test selection.",
                }
            ]
        )
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=usage,
        )


def test_preview_uses_ingest_summaries_without_summary_llm(monkeypatch, tmp_path):
    main = importlib.import_module("main")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "persona": {"text": "Macro investor focused on rates and valuations."},
            "email": {
                "digest_recipients": ["preview@example.com"],
                "digest_subject": "Ingest Summary Preview",
            },
            "additional_sources": {"enabled": True, "hours": 48},
            "limits": {
                "select_top_stories": 1,
                "final_top_stories": 1,
                "source_quotas": {"gmail": 0, "additional_source": 1},
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
            }
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            "https://example.com/markets/rates-reset": (
                "Rates reset changes software valuations and reprices growth names."
            )
        }
    )

    fetch_result = run_fetch_sources_job(
        config,
        source_fetcher=source_fetcher,
        article_fetcher=article_fetcher,
    )
    repository = get_repository_from_config(config)
    stories = repository.list_stories(source_type="additional_source")

    preview_config = dict(config)
    preview_config["development"] = dict(config["development"])
    preview_config["development"]["fake_inference"] = False
    monkeypatch.setattr(main, "OpenAI", RankingOnlyOpenAI)

    preview_result = main.preview_job(preview_config)

    assert fetch_result["status"] == "completed"
    assert fetch_result["usage_by_model"]["gpt-5-mini"]["total"] > 0
    assert stories[0]["summary_headline"]
    assert stories[0]["summary_body"]
    assert preview_result["status"] == "completed"
    assert preview_result["preview"] is not None
    assert "Rates reset changes software valuations" in preview_result["preview"]["body"]
