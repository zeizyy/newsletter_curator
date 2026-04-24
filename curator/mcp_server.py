from __future__ import annotations

import json
import sys

from . import config as config_module
from .repository import SQLiteRepository
from .story_feed import RECENT_STORY_WINDOW_HOURS, list_recent_story_feed, resolve_database_path

MCP_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_MCP_PROTOCOL_VERSIONS = {
    MCP_PROTOCOL_VERSION,
    "2025-06-18",
    "2025-03-26",
}
SERVER_NAME = "newsletter-curator-story-feed"
SERVER_VERSION = "0.2.0"
RECENT_STORIES_TOOL = "list_recent_stories"
SEARCH_RECENT_STORIES_TOOL = "search_recent_stories"
GET_STORY_DETAILS_TOOL = "get_story_details"
MIN_WINDOW_HOURS = 1
MAX_WINDOW_HOURS = 168
MAX_SEARCH_LIMIT = 12
DEFAULT_SEARCH_LIMIT = 8
DEFAULT_DETAIL_CHAR_LIMIT = 3500
MAX_DETAIL_CHAR_LIMIT = 12000


def _story_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "story_key",
            "source_type",
            "source_name",
            "subject",
            "url",
            "canonical_url",
            "anchor_text",
            "context",
            "category",
            "published_at",
            "first_seen_at",
            "last_seen_at",
            "effective_timestamp",
            "summary",
            "summary_headline",
            "summary_body",
            "article_fetched_at",
            "paywall_detected",
            "paywall_reason",
            "summarized_at",
        ],
        "properties": {
            "id": {"type": "integer"},
            "story_key": {"type": "string"},
            "source_type": {"type": "string"},
            "source_name": {"type": "string"},
            "subject": {"type": "string"},
            "url": {"type": "string"},
            "canonical_url": {"type": "string"},
            "anchor_text": {"type": "string"},
            "context": {"type": "string"},
            "category": {"type": "string"},
            "published_at": {"type": ["string", "null"]},
            "first_seen_at": {"type": "string"},
            "last_seen_at": {"type": "string"},
            "effective_timestamp": {"type": "string"},
            "summary": {"type": "string"},
            "summary_headline": {"type": "string"},
            "summary_body": {"type": "string"},
            "article_fetched_at": {"type": ["string", "null"]},
            "paywall_detected": {"type": "boolean"},
            "paywall_reason": {"type": ["string", "null"]},
            "summarized_at": {"type": ["string", "null"]},
        },
    }


def build_recent_stories_tool() -> dict:
    return {
        "name": RECENT_STORIES_TOOL,
        "title": "Recent Repository Stories",
        "description": "Returns stored newsletter story metadata from the repository without fetching or summarizing anything new.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "minimum": MIN_WINDOW_HOURS, "maximum": MAX_WINDOW_HOURS},
                "source_type": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["generated_at", "window_hours", "story_count", "stories"],
            "properties": {
                "generated_at": {"type": "string"},
                "window_hours": {"type": "integer"},
                "story_count": {"type": "integer"},
                "stories": {"type": "array", "items": _story_schema()},
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }


def build_search_recent_stories_tool() -> dict:
    snippet_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "title",
            "url",
            "source_name",
            "source_type",
            "published_at",
            "category",
            "summary_headline",
            "summary_body",
            "context",
        ],
        "properties": {
            "id": {"type": "integer"},
            "title": {"type": "string"},
            "url": {"type": "string"},
            "source_name": {"type": "string"},
            "source_type": {"type": "string"},
            "published_at": {"type": ["string", "null"]},
            "category": {"type": "string"},
            "summary_headline": {"type": "string"},
            "summary_body": {"type": "string"},
            "context": {"type": "string"},
        },
    }
    return {
        "name": SEARCH_RECENT_STORIES_TOOL,
        "title": "Search Recent Story Snippets",
        "description": "Searches recent repository stories and returns lightweight snippets first so the agent can decide whether it needs deeper detail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "hours": {"type": "integer", "minimum": MIN_WINDOW_HOURS, "maximum": MAX_WINDOW_HOURS},
                "source_type": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_LIMIT},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["generated_at", "query", "window_hours", "story_count", "stories"],
            "properties": {
                "generated_at": {"type": "string"},
                "query": {"type": "string"},
                "window_hours": {"type": "integer"},
                "story_count": {"type": "integer"},
                "stories": {"type": "array", "items": snippet_schema},
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }


def build_story_details_tool() -> dict:
    return {
        "name": GET_STORY_DETAILS_TOOL,
        "title": "Get Story Details",
        "description": "Returns one stored story with a bounded article excerpt. Use after searching snippets when deeper detail is required.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "story_id": {"type": "integer"},
                "max_article_chars": {"type": "integer", "minimum": 200, "maximum": MAX_DETAIL_CHAR_LIMIT},
            },
            "required": ["story_id"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "id",
                "title",
                "url",
                "source_name",
                "source_type",
                "published_at",
                "category",
                "summary_headline",
                "summary_body",
                "context",
                "article_excerpt",
                "article_excerpt_truncated",
            ],
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "url": {"type": "string"},
                "source_name": {"type": "string"},
                "source_type": {"type": "string"},
                "published_at": {"type": ["string", "null"]},
                "category": {"type": "string"},
                "summary_headline": {"type": "string"},
                "summary_body": {"type": "string"},
                "context": {"type": "string"},
                "article_excerpt": {"type": "string"},
                "article_excerpt_truncated": {"type": "boolean"},
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }


def _jsonrpc_result(message_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _jsonrpc_error(message_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def build_jsonrpc_error(code: int, message: str, *, message_id=None) -> dict:
    return _jsonrpc_error(message_id, code, message)


def _tool_error_result(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _tool_success_result(payload: dict) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
        "structuredContent": payload,
    }


def _parse_hours(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("hours must be an integer.")
    if value < MIN_WINDOW_HOURS or value > MAX_WINDOW_HOURS:
        raise ValueError(f"hours must be between {MIN_WINDOW_HOURS} and {MAX_WINDOW_HOURS}.")
    return value


def _parse_optional_string(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    normalized = value.strip()
    return normalized or None


def _parse_list_recent_stories_arguments(arguments: object) -> tuple[int, str | None]:
    if arguments in (None, {}):
        return RECENT_STORY_WINDOW_HOURS, None
    if not isinstance(arguments, dict):
        raise ValueError("list_recent_stories arguments must be an object.")
    unexpected = sorted(set(arguments) - {"hours", "source_type"})
    if unexpected:
        raise ValueError(f"Unsupported list_recent_stories arguments: {', '.join(unexpected)}")
    return (
        _parse_hours(arguments.get("hours"), default=RECENT_STORY_WINDOW_HOURS),
        _parse_optional_string(arguments.get("source_type"), field_name="source_type"),
    )


def _parse_search_recent_stories_arguments(arguments: object) -> tuple[str, int, str | None, int]:
    if not isinstance(arguments, dict):
        raise ValueError("search_recent_stories arguments must be an object.")
    unexpected = sorted(set(arguments) - {"query", "hours", "source_type", "limit"})
    if unexpected:
        raise ValueError(f"Unsupported search_recent_stories arguments: {', '.join(unexpected)}")
    query = _parse_optional_string(arguments.get("query"), field_name="query")
    if not query:
        raise ValueError("query is required.")
    limit = arguments.get("limit", DEFAULT_SEARCH_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer.")
    if limit < 1 or limit > MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}.")
    return (
        query,
        _parse_hours(arguments.get("hours"), default=RECENT_STORY_WINDOW_HOURS),
        _parse_optional_string(arguments.get("source_type"), field_name="source_type"),
        limit,
    )


def _parse_story_details_arguments(arguments: object) -> tuple[int, int]:
    if not isinstance(arguments, dict):
        raise ValueError("get_story_details arguments must be an object.")
    unexpected = sorted(set(arguments) - {"story_id", "max_article_chars"})
    if unexpected:
        raise ValueError(f"Unsupported get_story_details arguments: {', '.join(unexpected)}")
    story_id = arguments.get("story_id")
    if isinstance(story_id, bool) or not isinstance(story_id, int):
        raise ValueError("story_id must be an integer.")
    max_article_chars = arguments.get("max_article_chars", DEFAULT_DETAIL_CHAR_LIMIT)
    if isinstance(max_article_chars, bool) or not isinstance(max_article_chars, int):
        raise ValueError("max_article_chars must be an integer.")
    if max_article_chars < 200 or max_article_chars > MAX_DETAIL_CHAR_LIMIT:
        raise ValueError(f"max_article_chars must be between 200 and {MAX_DETAIL_CHAR_LIMIT}.")
    return story_id, max_article_chars


def _search_story_match(story: dict, query: str) -> bool:
    haystack = " ".join(
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
    terms = [term for term in query.lower().split() if term]
    return bool(terms) and all(term in haystack for term in terms)


def _story_title(story: dict) -> str:
    return (
        str(story.get("summary_headline", "")).strip()
        or str(story.get("anchor_text", "")).strip()
        or str(story.get("subject", "")).strip()
        or str(story.get("url", "")).strip()
    )


def _normalize_story_snippet(story: dict) -> dict:
    return {
        "id": int(story.get("id", 0) or 0),
        "title": _story_title(story),
        "url": str(story.get("url", "") or ""),
        "source_name": str(story.get("source_name", "") or ""),
        "source_type": str(story.get("source_type", "") or ""),
        "published_at": story.get("published_at"),
        "category": str(story.get("category", "") or ""),
        "summary_headline": str(story.get("summary_headline", "") or ""),
        "summary_body": str(story.get("summary_body", "") or str(story.get("summary", "") or "")),
        "context": str(story.get("context", "") or ""),
    }


def _trim_text(value: str, max_chars: int) -> tuple[str, bool]:
    normalized = str(value or "")
    if len(normalized) <= max_chars:
        return normalized, False
    return normalized[: max_chars - 1].rstrip() + "…", True


def search_recent_stories(
    config: dict,
    *,
    query: str,
    window_hours: int,
    source_type: str | None,
    limit: int,
) -> dict:
    payload = list_recent_story_feed(config, window_hours=window_hours, source_type=source_type)
    matching = [_normalize_story_snippet(story) for story in payload["stories"] if _search_story_match(story, query)]
    return {
        "generated_at": payload["generated_at"],
        "query": query,
        "window_hours": window_hours,
        "story_count": len(matching[:limit]),
        "stories": matching[:limit],
    }


def get_story_details(config: dict, *, story_id: int, max_article_chars: int) -> dict:
    repository = SQLiteRepository(resolve_database_path(config))
    repository.initialize()
    story = next((item for item in repository.list_stories() if int(item.get("id", 0) or 0) == story_id), None)
    if story is None:
        raise ValueError(f"Story {story_id} was not found.")
    article_excerpt, truncated = _trim_text(str(story.get("article_text", "") or ""), max_article_chars)
    return {
        "id": int(story["id"]),
        "title": _story_title(story),
        "url": str(story.get("url", "") or ""),
        "source_name": str(story.get("source_name", "") or ""),
        "source_type": str(story.get("source_type", "") or ""),
        "published_at": story.get("published_at"),
        "category": str(story.get("category", "") or ""),
        "summary_headline": str(story.get("summary_headline", "") or ""),
        "summary_body": str(story.get("summary_body", "") or str(story.get("summary", "") or "")),
        "context": str(story.get("context", "") or ""),
        "article_excerpt": article_excerpt,
        "article_excerpt_truncated": truncated,
    }


def supports_http_protocol_version(protocol_version: str | None) -> bool:
    if protocol_version is None:
        return True
    return str(protocol_version).strip() in SUPPORTED_MCP_PROTOCOL_VERSIONS


def handle_request(message: dict, *, config_path: str | None = None) -> dict | None:
    method = str(message.get("method", ""))
    message_id = message.get("id")
    params = message.get("params") or {}
    config = config_module.load_config(config_path)

    if method == "notifications/initialized":
        return None

    if method == "initialize":
        requested_protocol = str((params or {}).get("protocolVersion", "") or "").strip()
        protocol_version = requested_protocol if requested_protocol in SUPPORTED_MCP_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
        return _jsonrpc_result(
            message_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Use search_recent_stories for snippet-first retrieval, then get_story_details only when deeper detail is needed. "
                    "Use list_recent_stories when you need the broader repository view. This server is read-only."
                ),
            },
        )

    if method == "ping":
        return _jsonrpc_result(message_id, {})

    if method == "tools/list":
        return _jsonrpc_result(
            message_id,
            {"tools": [build_recent_stories_tool(), build_search_recent_stories_tool(), build_story_details_tool()]},
        )

    if method == "tools/call":
        tool_name = str(params.get("name", ""))
        try:
            if tool_name == RECENT_STORIES_TOOL:
                hours, source_type = _parse_list_recent_stories_arguments(params.get("arguments"))
                payload = list_recent_story_feed(config, window_hours=hours, source_type=source_type)
            elif tool_name == SEARCH_RECENT_STORIES_TOOL:
                query, hours, source_type, limit = _parse_search_recent_stories_arguments(params.get("arguments"))
                payload = search_recent_stories(
                    config,
                    query=query,
                    window_hours=hours,
                    source_type=source_type,
                    limit=limit,
                )
            elif tool_name == GET_STORY_DETAILS_TOOL:
                story_id, max_article_chars = _parse_story_details_arguments(params.get("arguments"))
                payload = get_story_details(config, story_id=story_id, max_article_chars=max_article_chars)
            else:
                return _jsonrpc_error(message_id, -32601, f"Unknown tool: {tool_name}")
        except Exception as exc:
            return _jsonrpc_result(message_id, _tool_error_result(str(exc)))
        return _jsonrpc_result(message_id, _tool_success_result(payload))

    if message_id is None:
        return None
    return _jsonrpc_error(message_id, -32601, f"Method not found: {method}")


def run_server(*, input_stream=None, output_stream=None, config_path: str | None = None) -> int:
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            print("Skipping invalid JSON-RPC message.", file=sys.stderr)
            continue
        response = handle_request(message, config_path=config_path)
        if response is None:
            continue
        output_stream.write(json.dumps(response, separators=(",", ":")) + "\n")
        output_stream.flush()
    return 0
