from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from curator import config as config_module
from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run, write_temp_config


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
    }


def test_mcp_rag_flow_prefers_snippets_before_bounded_detail(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")
    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CURATOR_MCP_TOKEN", "mcp-secret")

    config = config_module.load_config(str(config_path))
    repository = get_repository_from_config(config)
    run_id = create_completed_ingestion_run(repository, "additional_source")

    now = datetime.now(UTC)
    first_published_at = (now - timedelta(minutes=15)).isoformat()
    second_published_at = (now - timedelta(minutes=5)).isoformat()

    first_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Chip Ledger",
            "subject": "AI chips capex accelerates",
            "url": "https://example.com/chips/capex-accelerates",
            "anchor_text": "AI chips capex accelerates",
            "context": "Hyperscalers are increasing chip budgets and rack buildouts.",
            "category": "Tech company news & strategy",
            "published_at": first_published_at,
            "summary": "Chip capex is rising across the hyperscalers.",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        first_story_id,
        "A" * 600 + " detailed article body about AI chips and spending discipline.",
        summary_headline="AI chips capex accelerates",
        summary_body="Hyperscalers are raising chip and data center budgets.",
        summarized_at=first_published_at,
    )

    second_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Model Economics",
            "subject": "Inference margins tighten as chip demand climbs",
            "url": "https://example.com/chips/inference-margins",
            "anchor_text": "Inference margins tighten",
            "context": "Teams are trading off model quality against chip cost inflation.",
            "category": "Markets / stocks / macro / economy",
            "published_at": second_published_at,
            "summary": "Demand for accelerators is feeding back into inference economics.",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        second_story_id,
        "B" * 500 + " bounded article text about inference costs and accelerator demand.",
        summary_headline="Inference margins tighten",
        summary_body="Accelerator demand is putting pressure on inference unit economics.",
        summarized_at=second_published_at,
    )

    client = admin_app.app.test_client()

    search_response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search_recent_stories",
                "arguments": {
                    "query": "chip demand",
                    "hours": 48,
                    "limit": 5,
                },
            },
        },
        headers=_headers("mcp-secret"),
    )
    assert search_response.status_code == 200
    search_payload = search_response.get_json()["result"]["structuredContent"]
    assert search_payload["story_count"] == 1
    assert search_payload["stories"][0]["id"] == second_story_id
    assert "Accelerator demand" in search_payload["stories"][0]["summary_body"]
    assert "article_excerpt" not in search_payload["stories"][0]

    details_response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_story_details",
                "arguments": {
                    "story_id": second_story_id,
                    "max_article_chars": 240,
                },
            },
        },
        headers=_headers("mcp-secret"),
    )
    assert details_response.status_code == 200
    details_payload = details_response.get_json()["result"]["structuredContent"]
    assert details_payload["id"] == second_story_id
    assert details_payload["title"] == "Inference margins tighten"
    assert "Accelerator demand is putting pressure on inference unit economics." == details_payload["summary_body"]
    assert "article_excerpt" not in details_payload
    assert "context" not in details_payload

    broad_search_response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search_recent_stories",
                "arguments": {
                    "query": "ai chips",
                    "hours": 48,
                    "limit": 5,
                },
            },
        },
        headers=_headers("mcp-secret"),
    )
    assert broad_search_response.status_code == 200
    broad_search_payload = broad_search_response.get_json()["result"]["structuredContent"]
    assert broad_search_payload["story_count"] == 1
    assert broad_search_payload["stories"][0]["id"] == first_story_id
