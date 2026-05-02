from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from openai import OpenAI

from curator.config import load_config, merge_dicts
from curator.daily_news_agent import DailyNewsAgentService
from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run


pytestmark = pytest.mark.agent_eval


def _require_openai_api_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for real API agent evals")


def _agent_eval_config(tmp_path) -> dict:
    config = load_config()
    return merge_dicts(
        config,
        {
            "database": {"path": str(tmp_path / "curator.sqlite3")},
        },
    )


def _seed_chip_story(config: dict) -> dict:
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
    return {"id": story_id, "title": "AI chip capex accelerates", "url": "https://example.com/chips"}


def _agent_events(config: dict, *, history: list[dict], user_message: str) -> list[dict]:
    service = DailyNewsAgentService(
        config,
        server_url="",
        authorization="",
        client_factory=lambda: OpenAI(timeout=60.0, max_retries=2),
    )
    events = list(
        service.stream_reply(
            history=history,
            user_message=user_message,
            debug=True,
        )
    )
    return events


def _done_event(events: list[dict]) -> dict:
    return next(event for event in events if event["type"] == "done")


def _tool_call_names(events: list[dict]) -> list[str]:
    names: list[str] = []
    for event in events:
        if event["type"] != "debug":
            continue
        debug_event = event["event"]
        if debug_event.get("type") != "model_response":
            continue
        names.extend(debug_event.get("choice", {}).get("tool_call_names", []))
    return names


def test_daily_news_agent_answers_short_definition_without_token_limit_fallback(tmp_path):
    _require_openai_api_key()

    config = _agent_eval_config(tmp_path)

    events = _agent_events(
        config,
        history=[{"role": "user", "content": "what is capex?"}],
        user_message="what is capex?",
    )

    done_event = _done_event(events)
    answer = done_event["message"].lower()
    assert "capital expenditure" in answer or "capital expenses" in answer
    assert "hit the answer token limit" not in answer
    assert done_event["metadata"]["used_local_tool"] is False
    assert _tool_call_names(events) == []

    first_request = next(
        event["event"]
        for event in events
        if event["type"] == "debug" and event["event"].get("type") == "model_request"
    )
    assert first_request["max_completion_tokens"] == 2000


def test_daily_news_agent_uses_general_knowledge_for_background_followup(tmp_path):
    _require_openai_api_key()

    config = _agent_eval_config(tmp_path)
    _seed_chip_story(config)

    events = _agent_events(
        config,
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
    )

    done_event = next(event for event in events if event["type"] == "done")
    answer = done_event["message"].lower()
    assert "capital expenditure" in answer or "capital expenses" in answer
    assert "ai" in answer or "chip" in answer or "accelerator" in answer
    assert done_event["metadata"]["used_local_tool"] is False
    assert _tool_call_names(events) == []


def test_daily_news_agent_routes_headline_roundup_to_list_recent_stories(tmp_path):
    _require_openai_api_key()

    config = _agent_eval_config(tmp_path)
    _seed_chip_story(config)

    events = _agent_events(
        config,
        history=[{"role": "user", "content": "What happened today in the stored daily news corpus?"}],
        user_message="What happened today in the stored daily news corpus?",
    )

    done_event = _done_event(events)
    answer = done_event["message"].lower()
    assert done_event["metadata"]["used_local_tool"] is True
    assert "list_recent_stories" in _tool_call_names(events)
    assert "ai chip" in answer or "capex" in answer or "chip" in answer


def test_daily_news_agent_routes_stored_story_question_to_get_story_details(tmp_path):
    _require_openai_api_key()

    config = _agent_eval_config(tmp_path)
    story = _seed_chip_story(config)

    events = _agent_events(
        config,
        history=[
            {
                "role": "assistant",
                "content": (
                    f"Repository story identified: story_id={story['id']}; "
                    f"{story['title']} ({story['url']})."
                ),
            },
            {"role": "user", "content": "What did the stored story say about capex? Cite it."},
        ],
        user_message="What did the stored story say about capex? Cite it.",
    )

    done_event = _done_event(events)
    answer = done_event["message"].lower()
    assert done_event["metadata"]["used_local_tool"] is True
    assert "get_story_details" in _tool_call_names(events)
    assert "capital expenditure" in answer or "capex" in answer
    assert story["url"] in done_event["message"]
