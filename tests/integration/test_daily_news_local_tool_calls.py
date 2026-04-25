from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from curator.daily_news_agent import DailyNewsAgentService
from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run


def _tool_call(call_id: str, name: str, arguments: str):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class FakeToolCallingOpenAI:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.calls = 0
        self.request_kwargs: list[dict] = []

    def create(self, **kwargs):
        self.calls += 1
        self.request_kwargs.append(kwargs)
        if self.calls == 1:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                _tool_call(
                                    "call-list",
                                    "list_recent_stories",
                                    '{"hours":48,"limit":3}',
                                )
                            ],
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=11, completion_tokens=4, total_tokens=15),
            )
        if self.calls == 2:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                _tool_call(
                                    "call-detail",
                                    "get_story_details",
                                    '{"story_id":1,"max_article_chars":320}',
                                )
                            ],
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=13, completion_tokens=5, total_tokens=18),
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="AI chip capex accelerated. AI chip capex accelerates (https://example.com/chips).",
                        tool_calls=[],
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=17, completion_tokens=8, total_tokens=25),
        )


class FakeEmptyAfterToolOpenAI:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(
                id="chatcmpl-tool",
                model="gpt-5-mini",
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        message=SimpleNamespace(
                            role="assistant",
                            content="",
                            tool_calls=[
                                _tool_call(
                                    "call-list",
                                    "list_recent_stories",
                                    '{"hours":24,"limit":2}',
                                )
                            ],
                        ),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=21, completion_tokens=7, total_tokens=28),
            )
        return SimpleNamespace(
            id="chatcmpl-empty",
            model="gpt-5-mini",
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(role="assistant", content="", tool_calls=[]),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=31,
                completion_tokens=400,
                total_tokens=431,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=400),
            ),
        )


class FakeLargeToolResultOpenAI:
    def __init__(self, story_id: int):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.calls = 0
        self.story_id = story_id
        self.request_kwargs: list[dict] = []

    def create(self, **kwargs):
        self.calls += 1
        self.request_kwargs.append(kwargs)
        if self.calls == 1:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                _tool_call(
                                    "call-detail",
                                    "get_story_details",
                                    json.dumps({"story_id": self.story_id}),
                                )
                            ],
                        ),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=9, completion_tokens=3, total_tokens=12),
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="I can answer from the capped story summary.", tool_calls=[]),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=7, total_tokens=19),
        )


def test_daily_news_agent_uses_local_repository_tool_calls(tmp_path):
    config = {
        "database": {"path": str(tmp_path / "curator.sqlite3")},
        "daily_news_agent": {"max_output_tokens": 400, "snippet_limit": 3, "detail_char_limit": 320},
        "openai": {"reasoning_model": "gpt-5-mini"},
    }

    repository = get_repository_from_config(config)
    repository.initialize()
    run_id = create_completed_ingestion_run(repository, "additional_source")
    published_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Chip Ledger",
            "subject": "AI chip capex accelerates",
            "url": "https://example.com/chips",
            "anchor_text": "AI chip capex accelerates",
            "context": "Chip budgets are expanding.",
            "category": "Tech company news & strategy",
            "published_at": published_at,
            "summary": "Chip capex is accelerating.",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        "Cloud providers are expanding accelerator orders and data center commitments.",
        summary_headline="AI chip capex accelerates",
        summary_body="Chip capex is accelerating.",
        summarized_at=published_at,
    )

    fake_openai = FakeToolCallingOpenAI()
    service = DailyNewsAgentService(config, server_url="", authorization="", client_factory=lambda: fake_openai)
    events = list(
        service.stream_reply(
            history=[{"role": "user", "content": "What happened with chips?"}],
            user_message="What happened with chips?",
        )
    )

    assert [event["message"] for event in events if event["type"] == "status"] == [
        "Loading repository tools",
        "Repository tools ready",
        "Reading repository headlines",
        "Repository context loaded",
        "Reading repository snippets",
        "Repository context loaded",
    ]
    done_event = next(event for event in events if event["type"] == "done")
    assert "AI chip capex accelerated" in done_event["message"]
    assert done_event["metadata"]["used_mcp"] is False
    assert done_event["metadata"]["used_local_tool"] is True
    assert done_event["metadata"]["usage"]["total_tokens"] == 58
    first_request = fake_openai.request_kwargs[0]
    assert "max_completion_tokens" in first_request
    assert first_request["max_completion_tokens"] == 400
    assert "max_tokens" not in first_request
    tool_messages = [message for message in fake_openai.request_kwargs[2]["messages"] if message["role"] == "tool"]
    detail_tool_message = tool_messages[-1]
    detail_payload = json.loads(detail_tool_message["content"])
    assert detail_payload["summary_body"] == "Chip capex is accelerating."
    assert "article_excerpt" not in detail_payload
    assert "context" not in detail_payload


def test_daily_news_agent_caps_tool_results_before_next_model_round(tmp_path):
    config = {
        "database": {"path": str(tmp_path / "curator.sqlite3")},
        "daily_news_agent": {"max_output_tokens": 400, "tool_result_char_limit": 1000},
        "openai": {"reasoning_model": "gpt-5-mini"},
    }

    repository = get_repository_from_config(config)
    repository.initialize()
    run_id = create_completed_ingestion_run(repository, "additional_source")
    published_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Policy Wire",
            "subject": "Long policy story",
            "url": "https://example.com/policy",
            "anchor_text": "Long policy story",
            "context": "A compact context field should not be included in details.",
            "category": "Politics & policy",
            "published_at": published_at,
            "summary": "Short fallback summary.",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        "Full article text should not be sent to get_story_details.",
        summary_headline="Long policy story",
        summary_body="Long summary. " * 260,
        summarized_at=published_at,
    )

    fake_openai = FakeLargeToolResultOpenAI(story_id)
    service = DailyNewsAgentService(config, server_url="", authorization="", client_factory=lambda: fake_openai)
    events = list(
        service.stream_reply(
            history=[{"role": "user", "content": "Tell me about the policy story."}],
            user_message="Tell me about the policy story.",
            debug=True,
        )
    )

    next_round_tool_message = next(
        message for message in fake_openai.request_kwargs[1]["messages"] if message["role"] == "tool"
    )
    tool_payload = json.loads(next_round_tool_message["content"])
    assert tool_payload["tool_result_truncated"] is True
    assert tool_payload["truncation_reason"]
    assert "visible_prefix" in tool_payload

    done_event = next(event for event in events if event["type"] == "done")
    tool_result_event = next(event for event in done_event["metadata"]["debug_trace"] if event["type"] == "tool_result")
    assert tool_result_event["truncated_for_model"] is True


def test_daily_news_agent_debug_trace_explains_empty_model_output_after_tool(tmp_path):
    config = {
        "database": {"path": str(tmp_path / "curator.sqlite3")},
        "daily_news_agent": {"max_output_tokens": 400, "snippet_limit": 2},
        "openai": {"reasoning_model": "gpt-5-mini"},
    }

    repository = get_repository_from_config(config)
    repository.initialize()
    run_id = create_completed_ingestion_run(repository, "additional_source")
    published_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Chip Ledger",
            "subject": "AI chip capex accelerates",
            "url": "https://example.com/chips",
            "anchor_text": "AI chip capex accelerates",
            "context": "Chip budgets are expanding.",
            "category": "Tech company news & strategy",
            "published_at": published_at,
            "summary": "Chip capex is accelerating.",
        },
        ingestion_run_id=run_id,
    )

    fake_openai = FakeEmptyAfterToolOpenAI()
    service = DailyNewsAgentService(config, server_url="", authorization="", client_factory=lambda: fake_openai)
    events = list(
        service.stream_reply(
            history=[{"role": "user", "content": "What happened today?"}],
            user_message="What happened today?",
            debug=True,
        )
    )

    done_event = next(event for event in events if event["type"] == "done")
    assert done_event["message"].startswith("I hit the answer token limit")
    trace = done_event["metadata"]["debug_trace"]
    assert [event["type"] for event in trace].count("model_request") == 2

    empty_response = next(
        event
        for event in trace
        if event["type"] == "model_response" and event["round"] == 2
    )
    assert empty_response["response_id"] == "chatcmpl-empty"
    assert empty_response["choice"]["finish_reason"] == "length"
    assert empty_response["choice"]["has_content"] is False
    assert empty_response["choice"]["tool_call_count"] == 0
    assert empty_response["usage"]["completion_tokens"] == 400
    assert "completion_tokens_details" in empty_response["usage"]

    assert any(event["type"] == "empty_assistant_output" for event in trace)
    fallback_event = next(event for event in trace if event["type"] == "fallback_answer")
    assert fallback_event["used_local_tool"] is True
