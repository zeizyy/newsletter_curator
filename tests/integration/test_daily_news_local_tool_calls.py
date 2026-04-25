from __future__ import annotations

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
                    message=SimpleNamespace(
                        content="AI chip capex accelerated. AI chip capex accelerates (https://example.com/chips).",
                        tool_calls=[],
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=17, completion_tokens=8, total_tokens=25),
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
        "Reading repository snippets",
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
