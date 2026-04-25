from __future__ import annotations

import json
import sys

from . import config as config_module
from .repository_tools import (
    GET_STORY_DETAILS_TOOL,
    RECENT_STORIES_TOOL,
    SEARCH_RECENT_STORIES_TOOL,
    build_recent_stories_tool,
    build_search_recent_stories_tool,
    build_story_details_tool,
    get_story_details,
    list_recent_story_feed,
    parse_list_recent_stories_arguments,
    parse_search_recent_stories_arguments,
    parse_story_details_arguments,
    search_recent_stories,
)

MCP_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_MCP_PROTOCOL_VERSIONS = {
    MCP_PROTOCOL_VERSION,
    "2025-06-18",
    "2025-03-26",
}
SERVER_NAME = "newsletter-curator-story-feed"
SERVER_VERSION = "0.2.0"


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
                hours, source_type = parse_list_recent_stories_arguments(params.get("arguments"))
                payload = list_recent_story_feed(config, window_hours=hours, source_type=source_type)
            elif tool_name == SEARCH_RECENT_STORIES_TOOL:
                query, hours, source_type, limit = parse_search_recent_stories_arguments(
                    params.get("arguments")
                )
                payload = search_recent_stories(
                    config,
                    query=query,
                    window_hours=hours,
                    source_type=source_type,
                    limit=limit,
                )
            elif tool_name == GET_STORY_DETAILS_TOOL:
                story_id, max_article_chars = parse_story_details_arguments(params.get("arguments"))
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
