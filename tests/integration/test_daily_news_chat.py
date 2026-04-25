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
                "used_mcp": False,
                "used_local_tool": True,
                "used_web_search": False,
                "usage": {"total_tokens": 42},
            },
        }


def _create_logged_in_subscriber(admin_app_module, email_address: str):
    repository = admin_app_module.load_repository(admin_app_module.load_merged_config())
    subscriber = repository.upsert_subscriber(email_address)
    session = repository.create_subscriber_session(int(subscriber["id"]))
    return repository, subscriber, session


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

    config = main.load_config()
    repository = get_repository_from_config(config)
    repository.initialize()
    repository, _subscriber, subscriber_session = _create_logged_in_subscriber(
        admin_app,
        "reader@example.com",
    )

    client = admin_app.app.test_client()
    client.set_cookie(admin_app.SUBSCRIBER_SESSION_COOKIE, subscriber_session["token"])

    page_response = client.get("/daily-news")
    assert page_response.status_code == 200
    page = page_response.get_data(as_text=True)
    assert "Daily News Agent" in page
    assert "Ask the stored daily news corpus" in page
    assert "Subscriber Rail" in page
    assert "Control Room" not in page

    session_response = client.post("/api/daily-news/session")
    assert session_response.status_code == 200
    session_payload = session_response.get_json()
    session_id = session_payload["session_id"]
    assert session_payload["messages"] == []
    assert session_payload["usage"]["daily_token_limit"] == 50000

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
    assert history_payload["messages"][1]["metadata"]["used_mcp"] is False
    assert history_payload["messages"][1]["metadata"]["used_local_tool"] is True
    assert history_payload["messages"][1]["metadata"]["usage"]["total_tokens"] == 42
    assert history_payload["messages"][1]["metadata"]["daily_tokens_used"] == 42


def test_daily_news_chat_requires_openai_api_key(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config = main.load_config()
    repository = get_repository_from_config(config)
    repository.initialize()
    repository, _subscriber, subscriber_session = _create_logged_in_subscriber(
        admin_app,
        "reader@example.com",
    )

    client = admin_app.app.test_client()
    client.set_cookie(admin_app.SUBSCRIBER_SESSION_COOKIE, subscriber_session["token"])
    session_response = client.post("/api/daily-news/session")
    session_id = session_response.get_json()["session_id"]

    stream_response = client.post(
        "/api/daily-news/stream",
        json={"session_id": session_id, "message": "What happened in chips?"},
    )
    assert stream_response.status_code == 200
    body = stream_response.get_data(as_text=True)
    assert '"type":"error"' in body
    assert "OPENAI_API_KEY is not configured for the Daily News agent." in body

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
    repository, _subscriber, subscriber_session = _create_logged_in_subscriber(
        admin_app,
        "reader@example.com",
    )
    client.set_cookie(admin_app.SUBSCRIBER_SESSION_COOKIE, subscriber_session["token"])
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
    assert history_payload["messages"][1]["metadata"]["used_mcp"] is False
    assert history_payload["messages"][1]["metadata"]["used_local_tool"] is True
    assert history_payload["messages"][1]["metadata"]["mock_agent"] is True


def test_daily_news_chat_requires_subscriber_login(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))

    config = main.load_config()
    repository = get_repository_from_config(config)
    repository.initialize()

    client = admin_app.app.test_client()

    page_response = client.get("/daily-news")
    assert page_response.status_code == 302
    assert page_response.headers["Location"].endswith("/login")

    session_response = client.post("/api/daily-news/session")
    assert session_response.status_code == 302
    assert session_response.headers["Location"].endswith("/login")


def test_daily_news_chat_sessions_are_scoped_to_subscriber(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))

    config = main.load_config()
    repository = get_repository_from_config(config)
    repository.initialize()
    repository, _first_subscriber, first_session = _create_logged_in_subscriber(
        admin_app,
        "first@example.com",
    )
    _repository, _second_subscriber, second_session = _create_logged_in_subscriber(
        admin_app,
        "second@example.com",
    )

    first_client = admin_app.app.test_client()
    first_client.set_cookie(admin_app.SUBSCRIBER_SESSION_COOKIE, first_session["token"])
    session_id = first_client.post("/api/daily-news/session").get_json()["session_id"]

    second_client = admin_app.app.test_client()
    second_client.set_cookie(admin_app.SUBSCRIBER_SESSION_COOKIE, second_session["token"])
    history_response = second_client.get(f"/api/daily-news/session/{session_id}")

    assert history_response.status_code == 404


def test_daily_news_chat_enforces_daily_token_limit(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "daily_news_agent": {"daily_token_limit": 40},
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CURATOR_DAILY_NEWS_AGENT_MODE", "mock")

    config = main.load_config()
    repository = get_repository_from_config(config)
    repository.initialize()
    repository, subscriber, subscriber_session = _create_logged_in_subscriber(
        admin_app,
        "reader@example.com",
    )
    repository.record_daily_news_agent_usage(int(subscriber["id"]), total_tokens=40)

    client = admin_app.app.test_client()
    client.set_cookie(admin_app.SUBSCRIBER_SESSION_COOKIE, subscriber_session["token"])
    session_id = client.post("/api/daily-news/session").get_json()["session_id"]

    stream_response = client.post(
        "/api/daily-news/stream",
        json={"session_id": session_id, "message": "What happened in chips?"},
    )

    assert stream_response.status_code == 429
    assert "token limit reached" in stream_response.get_data(as_text=True)
