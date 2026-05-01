from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from .repository_tools import (
    DEFAULT_TOOL_RESULT_CHAR_LIMIT,
    MIN_TOOL_RESULT_CHAR_LIMIT,
    build_recent_stories_tool,
    build_story_details_tool,
    get_story_details,
    list_recent_stories,
    list_recent_story_feed,
)


STATUS_BY_EVENT_TYPE = {
    "tools.loading": "Loading repository tools",
    "tools.ready": "Repository tools ready",
    "tool.list_recent_stories.start": "Reading repository headlines",
    "tool.list_recent_stories.done": "Repository context loaded",
    "tool.get_story_details.start": "Reading repository snippets",
    "tool.get_story_details.done": "Repository context loaded",
}


SYSTEM_PROMPT = """You are the Daily News agent inside Newsletter Curator. Answer questions about the stored daily-news corpus and related background context concisely.

Tool routing:
- Use tools only when the latest user message asks for stored repository facts. Earlier turns may identify a story, but they are not themselves a new tool request.
- Answer directly for general knowledge, definitions, historical background, implications, synthesis, or "why it matters" follow-ups, even when the user says "this story." Label the answer as general context when that distinction matters.
- `list_recent_stories`: use for repository headline or roundup requests, including recent stories, top news, date ranges, today, or yesterday.
- `get_story_details`: use only when a specific repository story is identifiable from the conversation and the latest message asks what the stored story/source/article says, requests citation/source details, or asks you to verify a claim against that stored story.
- If the user intent is unclear, answer directly and offer to check the repository.

Examples:
- "For background, what does capex mean, and why does it matter for this story?" -> answer directly from general knowledge.
- "What did the stored story say about capex?" -> call `get_story_details` if the story is identifiable.
- "What happened today?" -> call `list_recent_stories`.

Answering rules:
- When relying on repository facts, cite the story title and URL if available.
- Do not show internal story metadata such as story IDs, story keys, ingestion IDs, or database fields in user-facing answers.
- If a tool result includes `tool_result_truncated: true`, continue from the visible summary and say the answer is based on limited detail.
- Use exact dates for relative-date questions when it improves clarity.
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
        "max_tool_rounds": _int_setting(agent_cfg, "max_tool_rounds", 2, 0),
        "repository_window_hours": _int_setting(agent_cfg, "mcp_window_hours", 48, 1),
        "snippet_limit": _int_setting(agent_cfg, "snippet_limit", 8, 1),
        "detail_char_limit": _int_setting(agent_cfg, "detail_char_limit", 3500, 500),
        "tool_result_char_limit": _int_setting(
            agent_cfg,
            "tool_result_char_limit",
            DEFAULT_TOOL_RESULT_CHAR_LIMIT,
            MIN_TOOL_RESULT_CHAR_LIMIT,
        ),
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


def _build_function_tool(tool_definition: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": str(tool_definition["name"]),
            "description": str(tool_definition.get("description", "")),
            "parameters": dict(tool_definition.get("inputSchema") or {"type": "object", "properties": {}}),
        },
    }


def _serialize_debug_value(value: object, *, max_chars: int = 4000) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        normalized = json.loads(json.dumps(value, sort_keys=True, default=str))
    except TypeError:
        normalized = str(value)
    serialized = json.dumps(normalized, sort_keys=True)
    if len(serialized) <= max_chars:
        return normalized
    return {
        "truncated": True,
        "preview": serialized[: max_chars - 1].rstrip() + "…",
    }


def _debug_usage_payload(usage: object) -> dict:
    if usage is None:
        return {}
    payload: dict[str, object] = {}
    for field_name in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_tokens_details",
        "completion_tokens_details",
    ):
        value = getattr(usage, field_name, None)
        if value is not None:
            payload[field_name] = _serialize_debug_value(value)
    return payload


def _debug_choice_payload(choice: object, choice_message: object, tool_calls: list, content: str) -> dict:
    payload: dict[str, object] = {
        "finish_reason": getattr(choice, "finish_reason", None),
        "message_role": getattr(choice_message, "role", None),
        "has_content": bool(content),
        "content_chars": len(content),
        "tool_call_count": len(tool_calls),
        "tool_call_names": [str(tool_call.function.name) for tool_call in tool_calls],
    }
    for field_name in ("refusal", "audio"):
        value = getattr(choice_message, field_name, None)
        if value:
            payload[field_name] = _serialize_debug_value(value)
    if content:
        payload["content_preview"] = _trim_text(content, max_chars=500)
    return payload


def _serialize_tool_result_for_model(tool_result: dict, *, max_chars: int) -> tuple[str, bool]:
    content = json.dumps(tool_result, sort_keys=True)
    if len(content) <= max_chars:
        return content, False

    truncated_payload = {
        "tool_result_truncated": True,
        "truncation_reason": "tool result exceeded the local agent cap before the next model round",
        "original_char_count": len(content),
        "visible_prefix": content[: max_chars - 1].rstrip() + "…",
    }
    return json.dumps(truncated_payload, sort_keys=True), True


def build_agent_tools(*, server_url: str, authorization: str, settings: dict) -> list[dict]:
    del server_url, authorization, settings
    return [
        _build_function_tool(build_recent_stories_tool()),
        _build_function_tool(build_story_details_tool()),
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
        debug: bool = False,
    ) -> Iterator[dict]:
        yield {"type": "status", "message": "Loading repository tools"}
        yield {"type": "status", "message": "Repository tools ready"}
        yield {"type": "status", "message": "Reading repository snippets"}

        payload = list_recent_story_feed(
            self._config,
            window_hours=self._settings["repository_window_hours"],
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
            if len([item for item in history if item.get("role") == "user"]) > 1:
                lines.append("")
                lines.append("This answer uses the current turn plus the existing chat session context.")
            message = "\n".join(lines)

        for chunk in [message[index : index + 80] for index in range(0, len(message), 80)]:
            yield {"type": "delta", "delta": chunk}

        metadata = {
            "used_mcp": False,
            "used_local_tool": True,
            "used_web_search": False,
            "usage": {
                "input_tokens": len(user_message.split()) + 25,
                "output_tokens": max(1, len(message.split())),
                "total_tokens": len(user_message.split()) + len(message.split()) + 25,
            },
            "mock_agent": True,
            "user_message": _trim_text(user_message, max_chars=self._settings["max_message_chars"]),
        }
        if debug:
            metadata["debug_mode"] = True
            metadata["reasoning_trace_available"] = False
            metadata["debug_trace"] = [
                {
                    "type": "note",
                    "message": "Mock mode does not expose the live model trace. Showing observable mock behavior only.",
                }
            ]

        yield {
            "type": "done",
            "message": message,
            "metadata": metadata,
        }


class DailyNewsAgentService:
    def __init__(self, config: dict, *, server_url: str, authorization: str, client_factory=OpenAI):
        self._client_factory = client_factory
        self._config = config
        self._settings = build_agent_settings(config)
        self._server_url = server_url
        self._authorization = authorization

    def _emit_status(self, event_type: str, last_status: str) -> tuple[str, dict | None]:
        next_status = STATUS_BY_EVENT_TYPE.get(event_type, "")
        if next_status and next_status != last_status:
            return next_status, {"type": "status", "message": next_status}
        return last_status, None

    def _append_debug_trace(self, trace: list[dict], entry: dict, *, debug: bool) -> dict | None:
        if not debug:
            return None
        trace.append(entry)
        return {"type": "debug", "event": entry}

    def _handle_local_tool_call(self, tool_name: str, arguments: dict) -> dict:
        if tool_name == "list_recent_stories":
            return list_recent_stories(
                self._config,
                window_hours=int(arguments.get("hours", self._settings["repository_window_hours"])),
                source_type=arguments.get("source_type"),
                limit=int(arguments.get("limit", self._settings["snippet_limit"])),
            )
        if tool_name == "get_story_details":
            return get_story_details(
                self._config,
                story_id=int(arguments["story_id"]),
                max_article_chars=int(
                    arguments.get("max_article_chars", self._settings["detail_char_limit"])
                ),
            )
        raise ValueError(f"Unknown local tool: {tool_name}")

    def stream_reply(
        self,
        *,
        history: list[dict],
        user_message: str,
        debug: bool = False,
    ) -> Iterator[dict]:
        client = self._client_factory()
        used_local_tool = False
        used_web_search = False
        last_status = ""
        usage_payload = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        debug_trace: list[dict] = []
        token_limited_response = False

        input_messages = _history_to_input(
            history,
            max_history_messages=self._settings["max_history_messages"],
            max_message_chars=self._settings["max_message_chars"],
        )
        if debug:
            note_event = self._append_debug_trace(
                debug_trace,
                {
                    "type": "note",
                    "message": "Hidden model reasoning is not available from the API. This debug panel shows the observable tool trace only.",
                },
                debug=debug,
            )
            if note_event is not None:
                yield note_event
        last_status, status_event = self._emit_status("tools.loading", last_status)
        if status_event is not None:
            yield status_event
        last_status, status_event = self._emit_status("tools.ready", last_status)
        if status_event is not None:
            yield status_event

        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *input_messages]
        message = ""
        tools = build_agent_tools(
            server_url=self._server_url,
            authorization=self._authorization,
            settings=self._settings,
        )
        max_tool_rounds = self._settings["max_tool_rounds"]
        max_model_rounds = max_tool_rounds + 1
        for round_index in range(max_model_rounds):
            tools_for_round = tools if round_index < max_tool_rounds else []
            debug_event = self._append_debug_trace(
                debug_trace,
                {
                    "type": "model_request",
                    "round": round_index + 1,
                    "model": self._settings["model"],
                    "max_completion_tokens": self._settings["max_output_tokens"],
                    "force_answer": not tools_for_round,
                    "message_count": len(messages),
                    "tool_names": [
                        str(tool.get("function", {}).get("name", ""))
                        for tool in tools_for_round
                        if isinstance(tool, dict)
                    ],
                },
                debug=debug,
            )
            if debug_event is not None:
                yield debug_event
            request_kwargs = {
                "model": self._settings["model"],
                "messages": messages,
                "max_completion_tokens": self._settings["max_output_tokens"],
            }
            if tools_for_round:
                request_kwargs["tools"] = tools_for_round
                request_kwargs["tool_choice"] = "auto"
            response = client.chat.completions.create(**request_kwargs)
            usage = getattr(response, "usage", None)
            if usage is not None:
                usage_payload["input_tokens"] += int(getattr(usage, "prompt_tokens", 0) or 0)
                usage_payload["output_tokens"] += int(getattr(usage, "completion_tokens", 0) or 0)
                usage_payload["total_tokens"] += int(getattr(usage, "total_tokens", 0) or 0)

            choice_message = response.choices[0].message
            choice = response.choices[0]
            if getattr(choice, "finish_reason", None) == "length":
                token_limited_response = True
            tool_calls = list(getattr(choice_message, "tool_calls", None) or [])
            content = str(getattr(choice_message, "content", "") or "").strip()
            debug_event = self._append_debug_trace(
                debug_trace,
                {
                    "type": "model_response",
                    "round": round_index + 1,
                    "response_id": getattr(response, "id", None),
                    "model": getattr(response, "model", None),
                    "choice": _debug_choice_payload(choice, choice_message, tool_calls, content),
                    "usage": _debug_usage_payload(usage),
                },
                debug=debug,
            )
            if debug_event is not None:
                yield debug_event

            assistant_message: dict[str, Any] = {"role": "assistant"}
            if content:
                assistant_message["content"] = content
            if tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": str(tool_call.id),
                        "type": "function",
                        "function": {
                            "name": str(tool_call.function.name),
                            "arguments": str(tool_call.function.arguments),
                        },
                    }
                    for tool_call in tool_calls
                ]
            messages.append(assistant_message)

            if not tool_calls:
                if debug and content:
                    debug_event = self._append_debug_trace(
                        debug_trace,
                        {
                            "type": "assistant_output",
                            "round": round_index + 1,
                            "content": _trim_text(content, max_chars=1200),
                        },
                        debug=debug,
                    )
                    if debug_event is not None:
                        yield debug_event
                elif debug:
                    debug_event = self._append_debug_trace(
                        debug_trace,
                        {
                            "type": "empty_assistant_output",
                            "round": round_index + 1,
                            "finish_reason": getattr(choice, "finish_reason", None),
                            "message": "The model returned no visible content and no tool calls.",
                        },
                        debug=debug,
                    )
                    if debug_event is not None:
                        yield debug_event
                message = content
                break

            for tool_call in tool_calls:
                tool_name = str(tool_call.function.name)
                last_status, status_event = self._emit_status(f"tool.{tool_name}.start", last_status)
                if status_event is not None:
                    yield status_event
                try:
                    arguments = json.loads(str(tool_call.function.arguments or "{}"))
                    if not isinstance(arguments, dict):
                        raise ValueError("Tool arguments must decode to an object.")
                    debug_event = self._append_debug_trace(
                        debug_trace,
                        {
                            "type": "tool_call",
                            "round": round_index + 1,
                            "tool_name": tool_name,
                            "arguments": _serialize_debug_value(arguments),
                        },
                        debug=debug,
                    )
                    if debug_event is not None:
                        yield debug_event
                    tool_result = self._handle_local_tool_call(tool_name, arguments)
                except Exception as exc:
                    tool_result = {"error": str(exc)}
                tool_content, tool_result_truncated = _serialize_tool_result_for_model(
                    tool_result,
                    max_chars=self._settings["tool_result_char_limit"],
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tool_call.id),
                        "content": tool_content,
                    }
                )
                debug_event = self._append_debug_trace(
                    debug_trace,
                    {
                        "type": "tool_result",
                        "round": round_index + 1,
                        "tool_name": tool_name,
                        "truncated_for_model": tool_result_truncated,
                        "model_content_chars": len(tool_content),
                        "result": _serialize_debug_value(tool_result),
                    },
                    debug=debug,
                )
                if debug_event is not None:
                    yield debug_event
                used_local_tool = True
                last_status, status_event = self._emit_status(f"tool.{tool_name}.done", last_status)
                if status_event is not None:
                    yield status_event

        if not message:
            debug_event = self._append_debug_trace(
                debug_trace,
                {
                    "type": "fallback_answer",
                    "message": "No visible assistant content was produced before the agent fallback was applied.",
                    "likely_token_limited": token_limited_response,
                    "max_tool_rounds": max_tool_rounds,
                    "round_limit": max_model_rounds,
                    "used_local_tool": used_local_tool,
                },
                debug=debug,
            )
            if debug_event is not None:
                yield debug_event
            if token_limited_response:
                message = (
                    "I hit the answer token limit after reading repository context, so I could not finish "
                    "a clean response. Please ask for a narrower slice or retry with a shorter date range."
                )
            else:
                message = "I could not produce an answer from the available repository context."

        for chunk in [message[index : index + 80] for index in range(0, len(message), 80)]:
            yield {"type": "delta", "delta": chunk}

        metadata = {
            "used_mcp": False,
            "used_local_tool": used_local_tool,
            "used_web_search": used_web_search,
            "usage": usage_payload,
            "user_message": _trim_text(user_message, max_chars=self._settings["max_message_chars"]),
        }
        if debug:
            metadata["debug_mode"] = True
            metadata["reasoning_trace_available"] = False
            metadata["debug_trace"] = debug_trace

        yield {
            "type": "done",
            "message": message,
            "metadata": metadata,
        }
