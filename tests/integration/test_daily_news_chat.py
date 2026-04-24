from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run, write_temp_config


class FakeDailyNewsAgentService:
    def __init__(self, config: dict, *, server_url: str, authorization: str, client_factory=None):
        del config, client_factory
        self.server_url = server_url
        self.authorization = authorization

    def stream_reply(self, *, history: list[dict], user_message: str):
        assert history[-1]["role"] == "user"
        assert history[-1]["content"] == user_message
        yield {"type": "status", "message": "Reading repository snippets"}
        yield {"type": "delta", "delta": "Repository says "}
        yield {"type": "delta", "delta": "chip spending rose."}
        yield {
            "type": "done",
            "message": "Repository says chip spending rose.",
            "metadata": {
                "used_mcp": True,
                "used_web_search": False,
                "usage": {"total_tokens": 42},
            },
        }


def test_daily_news_chat_page_and_session_flow(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "DailyNewsAgentService", FakeDailyNewsAgentService)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("CURATOR_PUBLIC_BASE_URL", "https://curator.example.com")
    monkeypatch.setenv("CURATOR_MCP_TOKEN", "mcp-secret")

    config = main.load_config()
    repository = get_repository_from_config(config)
    repository.initialize()

    client = admin_app.app.test_client()

    page_response = client.get("/daily-news")
    assert page_response.status_code == 200
    page = page_response.get_data(as_text=True)
    assert "Daily News Agent" in page
    assert "Ask the stored daily news corpus" in page

    session_response = client.post("/api/daily-news/session")
    assert session_response.status_code == 200
    session_payload = session_response.get_json()
    session_id = session_payload["session_id"]
    assert session_payload["messages"] == []

    stream_response = client.post(
        "/api/daily-news/stream",
        json={"session_id": session_id, "message": "What happened in chips?"},
    )
    assert stream_response.status_code == 200
    body = stream_response.get_data(as_text=True)
    assert '"type":"status"' in body
    assert '"type":"delta"' in body
    assert "Repository says chip spending rose." in body

    history_response = client.get(f"/api/daily-news/session/{session_id}")
    assert history_response.status_code == 200
    history_payload = history_response.get_json()
    assert [message["role"] for message in history_payload["messages"]] == ["user", "assistant"]
    assert history_payload["messages"][1]["metadata"]["used_mcp"] is True
    assert history_payload["messages"][1]["metadata"]["usage"]["total_tokens"] == 42


def test_daily_news_chat_reports_non_public_mcp_url(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("CURATOR_MCP_TOKEN", "mcp-secret")

    config = main.load_config()
    repository = get_repository_from_config(config)
    repository.initialize()

    client = admin_app.app.test_client()
    session_response = client.post("/api/daily-news/session")
    session_id = session_response.get_json()["session_id"]

    stream_response = client.post(
        "/api/daily-news/stream",
        json={"session_id": session_id, "message": "What happened in chips?"},
    )
    assert stream_response.status_code == 200
    body = stream_response.get_data(as_text=True)
    assert '"type":"error"' in body
    assert "Current MCP URL uses local host 'localhost'" in body

    history_response = client.get(f"/api/daily-news/session/{session_id}")
    history_payload = history_response.get_json()
    assert history_payload["messages"] == []


def test_daily_news_chat_mock_mode_uses_local_repository(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CURATOR_DAILY_NEWS_AGENT_MODE", "mock")

    config = main.load_config()
    repository = get_repository_from_config(config)
    run_id = create_completed_ingestion_run(repository, "additional_source")
    published_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Chip Ledger",
            "subject": "AI chip capex accelerates",
            "url": "https://example.com/chips",
            "anchor_text": "AI chip capex accelerates",
            "context": "Hyperscalers are increasing chip budgets.",
            "category": "Tech company news & strategy",
            "published_at": published_at,
            "summary": "Chip spending is rising across cloud providers.",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        "Cloud providers are increasing accelerator purchases and data center commitments.",
        summary_headline="AI chip capex accelerates",
        summary_body="Chip spending is rising across cloud providers.",
        summarized_at=published_at,
    )

    client = admin_app.app.test_client()
    session_id = client.post("/api/daily-news/session").get_json()["session_id"]

    stream_response = client.post(
        "/api/daily-news/stream",
        json={"session_id": session_id, "message": "What happened with chips?"},
    )
    assert stream_response.status_code == 200
    body = stream_response.get_data(as_text=True)
    assert '"type":"status"' in body
    assert "Repository-backed answer" in body
    assert "AI chip capex accelerates" in body
    assert "mock_agent" in body

    history_payload = client.get(f"/api/daily-news/session/{session_id}").get_json()
    assert [message["role"] for message in history_payload["messages"]] == ["user", "assistant"]
    assert history_payload["messages"][1]["metadata"]["used_mcp"] is True
    assert history_payload["messages"][1]["metadata"]["mock_agent"] is True
