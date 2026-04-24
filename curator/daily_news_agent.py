from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from .mcp_server import get_story_details, list_recent_story_feed


STATUS_BY_EVENT_TYPE = {
    "response.mcp_list_tools.in_progress": "Loading repository tools",
    "response.mcp_list_tools.completed": "Repository tools ready",
    "response.mcp_call.in_progress": "Reading repository snippets",
    "response.mcp_call.completed": "Repository context loaded",
    "response.web_search_call.searching": "Expanding with web search",
    "response.web_search_call.in_progress": "Running web search",
    "response.web_search_call.completed": "Web search finished",
}


SYSTEM_PROMPT = """You are the Daily News agent inside Newsletter Curator.

Your job is to answer questions about the daily news corpus with concise, source-grounded responses.

Rules:
- Prefer repository facts from the remote MCP server first.
- Start with repository search/snippet tools before requesting deeper story detail.
- Only call web search when the repository does not contain enough coverage, or when the user explicitly asks for information outside the stored news set.
- Keep token usage bounded. Do not request full story detail unless it is necessary for the answer.
- When you rely on a repository story, cite it inline with the story title and URL if available.
- If web search was needed, clearly separate that from repository-backed claims.
- If the user asks about relative dates like today or yesterday, use exact dates in your answer when it improves clarity.
"""


def _int_setting(config: dict, key: str, default: int, minimum: int) -> int:
    try:
        parsed = int(config.get(key, default))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def build_agent_settings(config: dict) -> dict:
    agent_cfg = config.get("daily_news_agent", {}) or {}
    openai_cfg = config.get("openai", {}) or {}
    return {
        "model": str(agent_cfg.get("model") or openai_cfg.get("reasoning_model") or "gpt-5-mini").strip(),
        "max_history_messages": _int_setting(agent_cfg, "max_history_messages", 8, 2),
        "max_message_chars": _int_setting(agent_cfg, "max_message_chars", 1600, 400),
        "max_output_tokens": _int_setting(agent_cfg, "max_output_tokens", 900, 200),
        "mcp_window_hours": _int_setting(agent_cfg, "mcp_window_hours", 48, 1),
        "snippet_limit": _int_setting(agent_cfg, "snippet_limit", 8, 1),
        "detail_char_limit": _int_setting(agent_cfg, "detail_char_limit", 3500, 500),
    }


def _trim_text(value: str, *, max_chars: int) -> str:
    normalized = str(value or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _history_to_input(history: list[dict], *, max_history_messages: int, max_message_chars: int) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in history[-max_history_messages:]:
        role = str(item.get("role", "")).strip().lower()
        if role not in {"user", "assistant"}:
            continue
        messages.append(
            {
                "role": role,
                "content": _trim_text(str(item.get("content", "")), max_chars=max_message_chars),
            }
        )
    return messages


def _build_mcp_tool(*, server_url: str, authorization: str, settings: dict) -> dict:
    return {
        "type": "mcp",
        "server_label": "daily_news",
        "server_description": "Stored daily news repository exposed through Newsletter Curator MCP.",
        "server_url": server_url,
        "authorization": authorization,
        "allowed_tools": ["search_recent_stories", "get_story_details"],
        "headers": {
            "MCP-Protocol-Version": "2025-11-25",
        },
        "require_approval": "never",
    }


def build_agent_tools(*, server_url: str, authorization: str, settings: dict) -> list[dict]:
    return [
        _build_mcp_tool(server_url=server_url, authorization=authorization, settings=settings),
        {"type": "web_search"},
    ]


LOCAL_MOCK_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "did",
    "does",
    "for",
    "from",
    "happen",
    "happened",
    "into",
    "latest",
    "more",
    "news",
    "show",
    "tell",
    "that",
    "the",
    "their",
    "there",
    "this",
    "today",
    "what",
    "with",
}


def _query_terms(value: str) -> list[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in value)
    terms: list[str] = []
    for term in cleaned.split():
        if len(term) < 3 or term in LOCAL_MOCK_STOPWORDS:
            continue
        if term not in terms:
            terms.append(term)
    return terms


def _mock_story_haystack(story: dict) -> str:
    return " ".join(
        [
            str(story.get("subject", "")),
            str(story.get("anchor_text", "")),
            str(story.get("context", "")),
            str(story.get("category", "")),
            str(story.get("summary", "")),
            str(story.get("summary_headline", "")),
            str(story.get("summary_body", "")),
            str(story.get("source_name", "")),
        ]
    ).lower()


def _rank_mock_stories(stories: list[dict], query: str, *, limit: int) -> list[dict]:
    terms = _query_terms(query)
    scored: list[tuple[int, dict]] = []
    for story in stories:
        haystack = _mock_story_haystack(story)
        score = sum(1 for term in terms if term in haystack)
        if score:
            scored.append((score, story))
    if not scored:
        return stories[:limit]
    scored.sort(
        key=lambda item: (
            item[0],
            str(item[1].get("effective_timestamp", "")),
            int(item[1].get("id", 0) or 0),
        ),
        reverse=True,
    )
    return [story for _score, story in scored[:limit]]


def _story_summary(story: dict) -> str:
    return (
        str(story.get("summary_body", "")).strip()
        or str(story.get("summary", "")).strip()
        or str(story.get("context", "")).strip()
    )


def _story_title(story: dict) -> str:
    return (
        str(story.get("summary_headline", "")).strip()
        or str(story.get("anchor_text", "")).strip()
        or str(story.get("subject", "")).strip()
        or "Untitled story"
    )


class MockDailyNewsAgentService:
    """Local-only deterministic agent for browser testing without remote MCP."""

    def __init__(self, config: dict, *, server_url: str = "", authorization: str = "", client_factory=None):
        del server_url, authorization, client_factory
        self._config = config
        self._settings = build_agent_settings(config)

    def stream_reply(
        self,
        *,
        history: list[dict],
        user_message: str,
    ) -> Iterator[dict]:
        yield {"type": "status", "message": "Loading repository tools"}
        yield {"type": "status", "message": "Repository tools ready"}
        yield {"type": "status", "message": "Reading repository snippets"}

        payload = list_recent_story_feed(
            self._config,
            window_hours=self._settings["mcp_window_hours"],
            source_type=None,
        )
        stories = _rank_mock_stories(
            list(payload.get("stories", []) or []),
            user_message,
            limit=min(3, self._settings["snippet_limit"]),
        )

        if not stories:
            message = "I did not find matching repository stories in the local mock corpus."
        else:
            first = stories[0]
            detail = get_story_details(
                self._config,
                story_id=int(first["id"]),
                max_article_chars=self._settings["detail_char_limit"],
            )
            lines = ["Repository-backed answer:"]
            for story in stories:
                title = _story_title(story)
                source = str(story.get("source_name", "")).strip() or str(story.get("source_type", "")).strip()
                summary = _story_summary(story)
                url = str(story.get("url", "")).strip()
                source_text = f" ({source})" if source else ""
                url_text = f" {url}" if url else ""
                lines.append(f"- {title}{source_text}: {summary}{url_text}")
            excerpt = str(detail.get("article_excerpt", "")).strip()
            if excerpt:
                lines.append("")
                lines.append(f"Detail from {detail['title']}: {_trim_text(excerpt, max_chars=320)}")
            if len([item for item in history if item.get("role") == "user"]) > 1:
                lines.append("")
                lines.append("This answer uses the current turn plus the existing chat session context.")
            message = "\n".join(lines)

        for chunk in [message[index : index + 80] for index in range(0, len(message), 80)]:
            yield {"type": "delta", "delta": chunk}

        yield {
            "type": "done",
            "message": message,
            "metadata": {
                "used_mcp": True,
                "used_web_search": False,
                "usage": {
                    "input_tokens": len(user_message.split()) + 25,
                    "output_tokens": max(1, len(message.split())),
                    "total_tokens": len(user_message.split()) + len(message.split()) + 25,
                },
                "mock_agent": True,
                "user_message": _trim_text(user_message, max_chars=self._settings["max_message_chars"]),
            },
        }


class DailyNewsAgentService:
    def __init__(self, config: dict, *, server_url: str, authorization: str, client_factory=OpenAI):
        self._client_factory = client_factory
        self._settings = build_agent_settings(config)
        self._server_url = server_url
        self._authorization = authorization

    def stream_reply(
        self,
        *,
        history: list[dict],
        user_message: str,
    ) -> Iterator[dict]:
        client = self._client_factory()
        used_mcp = False
        used_web_search = False
        response_text_parts: list[str] = []
        last_status = ""

        input_messages = _history_to_input(
            history,
            max_history_messages=self._settings["max_history_messages"],
            max_message_chars=self._settings["max_message_chars"],
        )

        with client.responses.stream(
            model=self._settings["model"],
            instructions=SYSTEM_PROMPT,
            input=input_messages,
            tools=build_agent_tools(
                server_url=self._server_url,
                authorization=self._authorization,
                settings=self._settings,
            ),
            max_output_tokens=self._settings["max_output_tokens"],
            parallel_tool_calls=False,
            truncation="auto",
        ) as stream:
            for event in stream:
                event_type = str(getattr(event, "type", "") or "")
                if event_type == "response.output_text.delta":
                    delta = str(getattr(event, "delta", "") or "")
                    if delta:
                        response_text_parts.append(delta)
                        yield {"type": "delta", "delta": delta}
                    continue

                if event_type.startswith("response.mcp_"):
                    used_mcp = True
                if event_type.startswith("response.web_search_"):
                    used_web_search = True

                next_status = STATUS_BY_EVENT_TYPE.get(event_type, "")
                if next_status and next_status != last_status:
                    last_status = next_status
                    yield {"type": "status", "message": next_status}

            final_response = stream.get_final_response()

        usage = getattr(final_response, "usage", None)
        usage_payload = {}
        if usage is not None:
            usage_payload = {
                "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
                "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            }

        message = "".join(response_text_parts).strip()
        if not message:
            message = "I could not produce an answer from the available repository context."

        yield {
            "type": "done",
            "message": message,
            "metadata": {
                "used_mcp": used_mcp,
                "used_web_search": used_web_search,
                "usage": usage_payload,
                "user_message": _trim_text(user_message, max_chars=self._settings["max_message_chars"]),
            },
        }
