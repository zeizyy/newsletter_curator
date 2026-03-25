from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
            raise AssertionError("Preview should reuse the salvaged ingest summary.")
        content = json.dumps(
            [
                {
                    "index": 1,
                    "category": "Science / space / frontier tech",
                    "score": 9.7,
                    "rationale": "Malformed-summary regression selection.",
                }
            ]
        )
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=usage,
        )


def test_malformed_summary_json_is_salvaged_for_persistence_and_preview(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": False},
            "email": {
                "digest_recipients": ["preview@example.com"],
                "digest_subject": "Malformed Summary Regression",
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
    recent_iso = (datetime.now(UTC) - timedelta(hours=2)).isoformat()

    source_fetcher = FakeSourceFetcher(
        [
            {
                "subject": "[space] Moon base roadmap",
                "from": "NYTimes Home",
                "source_name": "NYTimes Home",
                "source_type": "additional_source",
                "date": recent_iso,
                "url": "https://example.com/space/moon-base",
                "anchor_text": "NASA unveils moon base roadmap",
                "context": "Moon base roadmap context",
                "category": "Science / space / frontier tech",
            }
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            "https://example.com/space/moon-base": (
                "NASA unveils a decade roadmap for a permanent Moon base and suspends Gateway."
            )
        }
    )
    malformed_summary = (
        '{"headline":"NASA unveils ~$30B, decade roadmap for a permanent Moon base; Gateway suspended",'
        '"body":"Key takeaways:\\n- NASA commits ~$20B over the next 7 years and another ~\\$10B later.\\n\\n'
        'Why this matters to me: Procurement demand will widen across autonomy, power, and logistics."}'
    )

    monkeypatch.setattr(
        jobs,
        "score_story_candidates",
        lambda items, usage_by_model, top_stories, reasoning_model, **kwargs: [
            {
                **dict(items[0]),
                "score": 9.7,
                "rationale": "Malformed-summary regression selection.",
            }
        ],
    )
    monkeypatch.setattr(jobs, "summarize_article_with_llm", lambda *args, **kwargs: malformed_summary)

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
    assert len(stories) == 1
    assert stories[0]["summary_headline"] == (
        "NASA unveils ~$30B, decade roadmap for a permanent Moon base; Gateway suspended"
    )
    assert "~$10B later." in stories[0]["summary_body"]
    assert "\\$10B" not in stories[0]["summary_body"]
    assert stories[0]["summary_body"].startswith("Key takeaways:")
    assert preview_result["status"] == "completed"
    assert preview_result["preview"] is not None
    assert "Untitled" not in preview_result["preview"]["body"]
    assert '{"headline"' not in preview_result["preview"]["body"]
    assert "NASA unveils ~$30B, decade roadmap for a permanent Moon base; Gateway suspended" in (
        preview_result["preview"]["body"]
    )
