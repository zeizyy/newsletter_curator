from __future__ import annotations

import json
import sys

from . import config as config_module
from .story_feed import RECENT_STORY_WINDOW_HOURS, list_recent_story_feed

MCP_PROTOCOL_VERSION = "2025-11-25"
LEGACY_MCP_PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "newsletter-curator-story-feed"
SERVER_VERSION = "0.1.0"
RECENT_STORIES_TOOL = "list_recent_stories"
MIN_WINDOW_HOURS = 1
MAX_WINDOW_HOURS = 168


def build_recent_stories_tool() -> dict:
    story_schema = {
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
    return {
        "name": RECENT_STORIES_TOOL,
        "title": "Recent Repository Stories",
        "description": "Returns stored newsletter story metadata from the last 24 hours without fetching or summarizing anything new.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "minimum": MIN_WINDOW_HOURS,
                    "maximum": MAX_WINDOW_HOURS,
                },
                "source_type": {
                    "type": "string",
                },
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
                "stories": {"type": "array", "items": story_schema},
            },
        },
        "annotations": {
            "readOnlyHint": True,
            "openWorldHint": False,
        },
    }


def _jsonrpc_result(message_id, result: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "result": result,
    }


def _jsonrpc_error(message_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def build_jsonrpc_error(code: int, message: str, *, message_id=None) -> dict:
    return _jsonrpc_error(message_id, code, message)


def _tool_error_result(message: str) -> dict:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def _tool_success_result(payload: dict) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
        "structuredContent": payload,
    }


def _parse_list_recent_stories_arguments(arguments: object) -> tuple[int, str | None]:
    if arguments in (None, {}):
        return RECENT_STORY_WINDOW_HOURS, None
    if not isinstance(arguments, dict):
        raise ValueError("list_recent_stories arguments must be an object.")

    allowed_keys = {"hours", "source_type"}
    unexpected = sorted(set(arguments) - allowed_keys)
    if unexpected:
        raise ValueError(f"Unsupported list_recent_stories arguments: {', '.join(unexpected)}")

    raw_hours = arguments.get("hours", RECENT_STORY_WINDOW_HOURS)
    if isinstance(raw_hours, bool) or not isinstance(raw_hours, int):
        raise ValueError("hours must be an integer.")
    if raw_hours < MIN_WINDOW_HOURS or raw_hours > MAX_WINDOW_HOURS:
        raise ValueError(f"hours must be between {MIN_WINDOW_HOURS} and {MAX_WINDOW_HOURS}.")

    raw_source_type = arguments.get("source_type")
    if raw_source_type is None:
        source_type = None
    elif not isinstance(raw_source_type, str):
        raise ValueError("source_type must be a string.")
    else:
        source_type = raw_source_type.strip() or None

    return raw_hours, source_type


def supports_http_protocol_version(protocol_version: str | None) -> bool:
    if protocol_version is None:
        return True
    normalized = str(protocol_version).strip()
    return normalized in {MCP_PROTOCOL_VERSION, LEGACY_MCP_PROTOCOL_VERSION}


def handle_request(message: dict, *, config_path: str | None = None) -> dict | None:
    method = str(message.get("method", ""))
    message_id = message.get("id")
    params = message.get("params") or {}

    if method == "notifications/initialized":
        return None

    if method == "initialize":
        return _jsonrpc_result(
            message_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
                "instructions": (
                    "Use list_recent_stories to inspect stored repository stories from the last 24 hours. "
                    "This server is read-only and never fetches or summarizes new content."
                ),
            },
        )

    if method == "ping":
        return _jsonrpc_result(message_id, {})

    if method == "tools/list":
        return _jsonrpc_result(message_id, {"tools": [build_recent_stories_tool()]})

    if method == "tools/call":
        tool_name = str(params.get("name", ""))
        if tool_name != RECENT_STORIES_TOOL:
            return _jsonrpc_error(message_id, -32601, f"Unknown tool: {tool_name}")
        try:
            hours, source_type = _parse_list_recent_stories_arguments(params.get("arguments"))
            payload = list_recent_story_feed(
                config_module.load_config(config_path),
                window_hours=hours,
                source_type=source_type,
            )
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
