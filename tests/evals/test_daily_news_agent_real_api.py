from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from openai import OpenAI

from curator.daily_news_agent import DailyNewsAgentService
from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run


pytestmark = pytest.mark.agent_eval


def _require_openai_api_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for real API agent evals")


def test_daily_news_agent_uses_general_knowledge_for_background_followup(tmp_path):
    _require_openai_api_key()

    config = {
        "database": {"path": str(tmp_path / "curator.sqlite3")},
        "daily_news_agent": {
            "model": os.environ.get("CURATOR_AGENT_EVAL_MODEL", "gpt-5-mini"),
            "max_output_tokens": int(os.environ.get("CURATOR_AGENT_EVAL_MAX_OUTPUT_TOKENS", "900")),
            "snippet_limit": 3,
            "detail_char_limit": 900,
        },
        "openai": {"reasoning_model": "gpt-5-mini"},
    }

    repository = get_repository_from_config(config)
    repository.initialize()
    run_id = create_completed_ingestion_run(repository, "additional_source")
    published_at = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Chip Ledger",
            "subject": "AI chip capex accelerates",
            "url": "https://example.com/chips",
            "anchor_text": "AI chip capex accelerates",
            "context": "Hyperscalers are increasing accelerator and data center budgets.",
            "category": "Tech company news & strategy",
            "published_at": published_at,
            "summary": "Chip capital expenditure is rising across cloud providers.",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        "Cloud providers are expanding accelerator orders and data center commitments.",
        summary_headline="AI chip capex accelerates",
        summary_body="Chip capital expenditure is rising across cloud providers.",
        summarized_at=published_at,
    )

    service = DailyNewsAgentService(
        config,
        server_url="",
        authorization="",
        client_factory=lambda: OpenAI(timeout=60.0, max_retries=2),
    )
    events = list(
        service.stream_reply(
            history=[
                {"role": "user", "content": "What happened with AI chip spending?"},
                {
                    "role": "assistant",
                    "content": (
                        "Repository-grounded: AI chip capital expenditure is rising across "
                        "cloud providers. AI chip capex accelerates (https://example.com/chips)."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "For background, what does capex mean, and why does it matter for this story?"
                    ),
                },
            ],
            user_message="For background, what does capex mean, and why does it matter for this story?",
            debug=True,
        )
    )

    done_event = next(event for event in events if event["type"] == "done")
    answer = done_event["message"].lower()
    assert "capital expenditure" in answer or "capital expenses" in answer
    assert "ai" in answer or "chip" in answer or "accelerator" in answer
    assert done_event["metadata"]["used_local_tool"] is False

    tool_call_events = [
        event
        for event in events
        if event["type"] == "debug"
        and event["event"].get("type") == "model_response"
        and event["event"].get("choice", {}).get("tool_call_count", 0) > 0
    ]
    assert tool_call_events == []
