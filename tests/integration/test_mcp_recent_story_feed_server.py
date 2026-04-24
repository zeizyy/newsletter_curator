from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
import stat
import subprocess
import sys

from curator import config as config_module
from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run, write_temp_config


def _send_message(process: subprocess.Popen[str], payload: dict) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _read_message(process: subprocess.Popen[str]) -> dict:
    assert process.stdout is not None
    line = process.stdout.readline()
    if line:
        return json.loads(line)
    stderr_output = process.stderr.read() if process.stderr is not None else ""
    raise AssertionError(f"Server exited before responding. stderr={stderr_output!r}")


def _call_tool(process: subprocess.Popen[str], *, call_id: int, arguments: dict | None = None) -> dict:
    _send_message(
        process,
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": "list_recent_stories", "arguments": arguments or {}},
        },
    )
    return _read_message(process)


def _set_story_first_seen(repository, story_id: int, timestamp: str) -> None:
    with repository.connect() as connection:
        connection.execute(
            """
            UPDATE fetched_stories
            SET first_seen_at = ?, last_seen_at = ?
            WHERE id = ?
            """,
            (timestamp, timestamp, story_id),
        )


def test_mcp_server_lists_recent_repository_stories_without_mutating_db(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    config = config_module.load_config(str(config_path))
    repository = get_repository_from_config(config)
    run_id = create_completed_ingestion_run(repository, "additional_source")

    now = datetime.now(UTC)
    very_recent = (now - timedelta(minutes=10)).isoformat()
    recent = (now - timedelta(hours=2)).isoformat()
    stale = (now - timedelta(hours=30)).isoformat()

    recent_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Macro Wire",
            "subject": "Rates reset",
            "url": "https://example.com/markets/rates-reset",
            "anchor_text": "Rates reset changes software valuations",
            "context": "Stored repository context",
            "category": "Markets / stocks / macro / economy",
            "published_at": recent,
            "summary": "Stored short summary",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        recent_story_id,
        "Article text that must not be exposed.",
        summary_headline="Rates reset",
        summary_body="Software multiples moved after the rates reset.",
        summarized_at=recent,
    )

    fallback_story_id = repository.upsert_story(
        {
            "source_type": "gmail",
            "source_name": "AI Infra",
            "subject": "Cloud budget changes",
            "url": "https://example.com/ai/cloud-budgets",
            "anchor_text": "Cloud budgets reset",
            "context": "Gmail-derived context",
            "category": "Tech company news & strategy",
            "published_at": "",
            "summary": "Fallback timestamp summary",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        fallback_story_id,
        "Another article body that must stay private.",
        paywall_detected=True,
        paywall_reason="metered",
        summary_headline="Cloud budgets",
        summary_body="Budget owners reset infra spend expectations.",
        summarized_at=very_recent,
    )
    _set_story_first_seen(repository, fallback_story_id, very_recent)

    stale_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Old Wire",
            "subject": "Stale story",
            "url": "https://example.com/old/stale-story",
            "anchor_text": "Stale story should not appear",
            "context": "Too old for the feed",
            "category": "Markets / stocks / macro / economy",
            "published_at": stale,
            "summary": "Old summary",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        stale_story_id,
        "Stale article body.",
        summary_headline="Old headline",
        summary_body="Old body",
        summarized_at=stale,
    )

    database_path = Path(config["database"]["path"])
    original_mode = stat.S_IMODE(database_path.stat().st_mode)
    database_path.chmod(0o444)

    repo_root = Path(__file__).resolve().parents[2]
    process = subprocess.Popen(
        [sys.executable, str(repo_root / "scripts" / "newsletter_mcp_server.py")],
        cwd=repo_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "NEWSLETTER_CONFIG": str(config_path)},
    )
    try:
        _send_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0.0.0"},
                },
            },
        )
        initialize_response = _read_message(process)
        assert initialize_response["result"]["protocolVersion"] == "2025-11-25"
        assert initialize_response["result"]["capabilities"] == {"tools": {}}

        _send_message(
            process,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )
        _send_message(
            process,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools_response = _read_message(process)
        tools = tools_response["result"]["tools"]
        tool_by_name = {tool["name"]: tool for tool in tools}
        assert set(tool_by_name) == {
            "list_recent_stories",
            "search_recent_stories",
            "get_story_details",
        }
        assert tool_by_name["list_recent_stories"]["annotations"]["readOnlyHint"] is True
        assert tool_by_name["list_recent_stories"]["inputSchema"]["properties"]["hours"]["maximum"] == 168
        assert (
            tool_by_name["list_recent_stories"]["inputSchema"]["properties"]["source_type"]["type"]
            == "string"
        )
        assert tool_by_name["search_recent_stories"]["inputSchema"]["required"] == ["query"]
        assert tool_by_name["get_story_details"]["inputSchema"]["required"] == ["story_id"]

        _send_message(
            process,
            {"jsonrpc": "2.0", "id": 99, "method": "ping", "params": {}},
        )
        ping_response = _read_message(process)
        assert ping_response["result"] == {}

        call_response = _call_tool(process, call_id=3)
        hours_filtered_response = _call_tool(process, call_id=4, arguments={"hours": 1})
        source_filtered_response = _call_tool(
            process,
            call_id=5,
            arguments={"source_type": "gmail"},
        )
        invalid_response = _call_tool(process, call_id=6, arguments={"hours": 999})
    finally:
        if process.stdin is not None:
            process.stdin.close()
        process.terminate()
        process.wait(timeout=5)
        database_path.chmod(original_mode)

    result = call_response["result"]
    assert result.get("isError") is not True
    payload = result["structuredContent"]
    assert payload["window_hours"] == 24
    assert payload["story_count"] == 2
    assert [story["id"] for story in payload["stories"]] == [fallback_story_id, recent_story_id]

    first_story = payload["stories"][0]
    assert first_story["published_at"] is None
    assert first_story["effective_timestamp"] == very_recent
    assert first_story["paywall_detected"] is True
    assert first_story["paywall_reason"] == "metered"
    assert "article_text" not in first_story

    second_story = payload["stories"][1]
    assert second_story["published_at"] == recent
    assert second_story["summary_headline"] == "Rates reset"
    assert second_story["summary_body"] == "Software multiples moved after the rates reset."

    rendered_text = result["content"][0]["text"]
    assert json.loads(rendered_text)["story_count"] == 2
    assert stale_story_id not in {story["id"] for story in payload["stories"]}

    hours_filtered_result = hours_filtered_response["result"]
    assert hours_filtered_result.get("isError") is not True
    hours_filtered_payload = hours_filtered_result["structuredContent"]
    assert hours_filtered_payload["window_hours"] == 1
    assert [story["id"] for story in hours_filtered_payload["stories"]] == [fallback_story_id]

    source_filtered_result = source_filtered_response["result"]
    assert source_filtered_result.get("isError") is not True
    source_filtered_payload = source_filtered_result["structuredContent"]
    assert source_filtered_payload["story_count"] == 1
    assert [story["id"] for story in source_filtered_payload["stories"]] == [fallback_story_id]
    assert source_filtered_payload["stories"][0]["source_type"] == "gmail"

    invalid_result = invalid_response["result"]
    assert invalid_result["isError"] is True
    assert "hours must be between 1 and 168" in invalid_result["content"][0]["text"]
