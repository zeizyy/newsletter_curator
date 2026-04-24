from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta

from curator import config as config_module
from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run, write_temp_config


def _seed_recent_story(repository) -> int:
    now = datetime.now(UTC)
    published_at = (now - timedelta(minutes=20)).isoformat()
    run_id = create_completed_ingestion_run(repository, "gmail")
    story_id = repository.upsert_story(
        {
            "source_type": "gmail",
            "source_name": "AI Infra",
            "subject": "Remote MCP story",
            "url": "https://example.com/ai/remote-mcp",
            "anchor_text": "Remote MCP story",
            "context": "Remote MCP context",
            "category": "Tech company news & strategy",
            "published_at": published_at,
            "summary": "Remote MCP short summary",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        "Private article text.",
        summary_headline="Remote MCP story",
        summary_body="Remote HTTP MCP served a stored story.",
        summarized_at=published_at,
    )
    return story_id


def _headers(token: str, *, origin: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }
    if origin is not None:
        headers["Origin"] = origin
    return headers


def test_http_mcp_route_lists_recent_stories(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")
    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CURATOR_MCP_TOKEN", "mcp-secret")
    monkeypatch.setenv("CURATOR_PUBLIC_BASE_URL", "https://curator.example.com")

    config = config_module.load_config(str(config_path))
    repository = get_repository_from_config(config)
    story_id = _seed_recent_story(repository)

    client = admin_app.app.test_client()
    initialize_response = client.post(
        "/mcp",
        json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0.0.0"},
                },
            },
        headers=_headers("mcp-secret", origin="https://curator.example.com"),
    )
    assert initialize_response.status_code == 200
    initialize_payload = initialize_response.get_json()
    assert initialize_payload["result"]["serverInfo"]["name"] == "newsletter-curator-story-feed"
    assert initialize_response.headers["MCP-Protocol-Version"] == "2025-11-25"
    assert initialize_payload["result"]["protocolVersion"] == "2025-06-18"

    tools_response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=_headers("mcp-secret"),
    )
    assert tools_response.status_code == 200
    tools_payload = tools_response.get_json()
    tool_names = {tool["name"] for tool in tools_payload["result"]["tools"]}
    assert tool_names == {"list_recent_stories", "search_recent_stories", "get_story_details"}

    call_response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_recent_stories", "arguments": {"source_type": "gmail"}},
        },
        headers=_headers("mcp-secret"),
    )
    assert call_response.status_code == 200
    call_payload = call_response.get_json()
    structured = call_payload["result"]["structuredContent"]
    assert structured["story_count"] == 1
    assert structured["stories"][0]["id"] == story_id
    assert structured["stories"][0]["source_type"] == "gmail"

    search_response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "search_recent_stories",
                "arguments": {"query": "remote mcp", "limit": 3},
            },
        },
        headers=_headers("mcp-secret"),
    )
    assert search_response.status_code == 200
    search_payload = search_response.get_json()["result"]["structuredContent"]
    assert search_payload["story_count"] == 1
    assert search_payload["stories"][0]["id"] == story_id

    details_response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "get_story_details",
                "arguments": {"story_id": story_id, "max_article_chars": 200},
            },
        },
        headers=_headers("mcp-secret"),
    )
    assert details_response.status_code == 200
    details_payload = details_response.get_json()["result"]["structuredContent"]
    assert details_payload["id"] == story_id
    assert details_payload["article_excerpt"] == "Private article text."


def test_http_mcp_route_rejects_invalid_origin_and_unsupported_protocol(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")
    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CURATOR_MCP_TOKEN", "mcp-secret")
    monkeypatch.setenv("CURATOR_PUBLIC_BASE_URL", "https://curator.example.com")

    client = admin_app.app.test_client()

    origin_response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers=_headers("mcp-secret", origin="https://evil.example.com"),
    )
    assert origin_response.status_code == 403
    assert origin_response.get_json()["error"]["message"] == "Forbidden origin."

    protocol_response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers={
            "Authorization": "Bearer mcp-secret",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "1999-01-01",
        },
    )
    assert protocol_response.status_code == 400
    assert "Unsupported MCP-Protocol-Version" in protocol_response.get_json()["error"]["message"]


def test_http_mcp_route_requires_token_and_returns_405_without_sse(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")
    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CURATOR_MCP_TOKEN", "mcp-secret")

    client = admin_app.app.test_client()
    unauthorized_response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert unauthorized_response.status_code == 401
    assert unauthorized_response.get_json()["error"]["message"] == "Unauthorized."

    get_response = client.get(
        "/mcp",
        headers={
            "Authorization": "Bearer mcp-secret",
            "Accept": "text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        },
    )
    assert get_response.status_code == 405

    notification_response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        headers=_headers("mcp-secret"),
    )
    assert notification_response.status_code == 202
    assert notification_response.get_data(as_text=True) == ""

    delete_response = client.delete("/mcp", headers=_headers("mcp-secret"))
    assert delete_response.status_code == 405
