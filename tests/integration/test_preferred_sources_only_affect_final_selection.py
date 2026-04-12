from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from curator.jobs import get_repository_from_config
from tests.fakes import FakeGmailService
from tests.helpers import create_completed_ingestion_run, write_temp_config


class PreferredSourceBoundaryOpenAI:
    prompts: list[dict] = []

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    @classmethod
    def reset(cls) -> None:
        cls.prompts = []

    def create(self, *, model: str, messages: list[dict]):
        prompt_text = "\n".join(message["content"] for message in messages)
        lowered = prompt_text.lower()
        PreferredSourceBoundaryOpenAI.prompts.append({"model": model, "prompt": prompt_text})

        if "deserve expensive summaries" in lowered:
            assert "ai wire" not in lowered
            content = json.dumps(
                [
                    {"index": 1, "score": 9.1, "rationale": "Keep the first candidate."},
                    {"index": 2, "score": 8.9, "rationale": "Keep the second candidate."},
                ]
            )
        elif "select the top stories" in lowered:
            assert "hard filter" in lowered
            assert "ai wire" in lowered
            assert "rates reset changes software valuations" not in lowered
            content = json.dumps(
                [
                    {
                        "index": 1,
                        "category": "AI & ML industry developments",
                        "score": 9.9,
                        "rationale": "Preferred source passed the hard filter.",
                    }
                ]
            )
        else:
            assert "ai wire" not in lowered
            if "open model pricing changed" in lowered:
                content = json.dumps(
                    {
                        "headline": "Open model pricing changed",
                        "body": "\n".join(
                            [
                                "Key takeaways",
                                "- Open model pricing changed and shifts inference budgets.",
                                "Why this matters to me",
                                "This matters because model cost changes alter deployment economics.",
                            ]
                        ),
                    }
                )
            elif "rates reset changes software valuations" in lowered:
                content = json.dumps(
                    {
                        "headline": "Rates reset changes software valuations",
                        "body": "\n".join(
                            [
                                "Key takeaways",
                                "- Rates reset changes software valuations in public markets.",
                                "Why this matters to me",
                                "This matters because repricing can reset investor expectations.",
                            ]
                        ),
                    }
                )
            else:
                raise AssertionError("Unexpected summary prompt.")

        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=usage,
        )


def _seed_story_catalog(repository) -> None:
    recent_base = datetime.now(UTC) - timedelta(hours=2)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    for source_name, subject, url, anchor_text, context, category in (
        (
            "Macro Wire",
            "[markets] Rates reset",
            "https://example.com/markets/rates-reset",
            "Rates reset changes software valuations",
            "Macro context for valuations and rates.",
            "Markets / stocks / macro / economy",
        ),
        (
            "AI Wire",
            "[ai] Open model pricing changed",
            "https://example.com/ai/model-pricing",
            "Open model pricing changed",
            "AI pricing and chip context.",
            "AI & ML industry developments",
        ),
    ):
        story_id = repository.upsert_story(
            {
                "source_type": "additional_source",
                "source_name": source_name,
                "subject": subject,
                "url": url,
                "anchor_text": anchor_text,
                "context": context,
                "category": category,
                "published_at": recent_base.isoformat(),
                "summary": anchor_text,
            },
            ingestion_run_id=ingestion_run_id,
        )
        repository.upsert_article_snapshot(
            story_id,
            f"{anchor_text} article text.",
            summary_headline=anchor_text,
            summary_body=anchor_text,
            summary_model="gpt-5-mini",
            summarized_at=(recent_base + timedelta(minutes=5)).isoformat(),
        )


def test_preferred_sources_only_affect_final_selection(monkeypatch, tmp_path):
    main = importlib.import_module("main")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["reader@example.com"],
                "digest_subject": "Preferred Source Digest",
            },
            "additional_sources": {"enabled": True, "hours": 24},
            "limits": {
                "select_top_stories": 2,
                "final_top_stories": 1,
                "source_quotas": {"gmail": 0, "additional_source": 1},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(main, "OpenAI", PreferredSourceBoundaryOpenAI)

    PreferredSourceBoundaryOpenAI.reset()
    config = main.load_config()
    repository = get_repository_from_config(config)
    _seed_story_catalog(repository)
    repository.set_source_selection(
        source_type="additional_source",
        source_name="AI Wire",
        enabled=True,
    )

    subscriber = repository.upsert_subscriber("reader@example.com")
    repository.upsert_subscriber_profile(
        int(subscriber["id"]),
        preferred_sources=["AI Wire"],
    )

    sent_messages: list[dict] = []

    def fake_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        sent_messages.append({"to": to_address, "subject": subject, "body": body, "html_body": html_body or ""})

    monkeypatch.setattr(main, "send_email", fake_send_email)

    result = main.run_job(config, FakeGmailService(messages=[]))

    assert result["status"] == "completed"
    assert result["personalized_delivery"] is True
    assert sent_messages[0]["to"] == "reader@example.com"
    assert "Open model pricing changed" in sent_messages[0]["body"]
    assert "Rates reset changes software valuations" not in sent_messages[0]["body"]

    ranking_prompts = [
        prompt["prompt"].lower()
        for prompt in PreferredSourceBoundaryOpenAI.prompts
        if "select the top stories" in prompt["prompt"].lower()
    ]
    scoring_prompts = [
        prompt["prompt"].lower()
        for prompt in PreferredSourceBoundaryOpenAI.prompts
        if "deserve expensive summaries" in prompt["prompt"].lower()
    ]
    summary_prompts = [
        prompt["prompt"].lower()
        for prompt in PreferredSourceBoundaryOpenAI.prompts
        if "write a concise summary of the article below." in prompt["prompt"].lower()
    ]

    assert ranking_prompts
    assert all("ai wire" in prompt for prompt in ranking_prompts)
    assert all("rates reset changes software valuations" not in prompt for prompt in ranking_prompts)
    assert all("ai wire" not in prompt for prompt in scoring_prompts)
    assert all("ai wire" not in prompt for prompt in summary_prompts)
