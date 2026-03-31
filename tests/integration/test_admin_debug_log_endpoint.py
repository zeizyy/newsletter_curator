from __future__ import annotations

import importlib
import json

from curator.observability import emit_event
from tests.helpers import write_temp_config


def _build_client(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")
    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    return admin_app.app.test_client()


def test_admin_debug_log_endpoint_requires_dedicated_token(monkeypatch, tmp_path):
    log_path = tmp_path / "debug.ndjson"
    log_path.write_text('{"event":"existing"}\n', encoding="utf-8")
    monkeypatch.setenv("CURATOR_DEBUG_LOG_PATH", str(log_path))
    monkeypatch.setenv("CURATOR_DEBUG_LOG_TOKEN", "debug-secret")
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/debug/logs")

    assert response.status_code == 401
    assert response.get_json()["error"] == "Unauthorized."


def test_admin_debug_log_endpoint_returns_bounded_tail(monkeypatch, tmp_path):
    log_path = tmp_path / "debug.ndjson"
    monkeypatch.setenv("CURATOR_DEBUG_LOG_PATH", str(log_path))
    monkeypatch.setenv("CURATOR_DEBUG_LOG_TOKEN", "debug-secret")
    emit_event("debug_event_one", index=1)
    emit_event("debug_event_two", index=2)
    emit_event("debug_event_three", index=3)

    client = _build_client(monkeypatch, tmp_path)
    response = client.get(
        "/debug/logs?lines=2",
        headers={"Authorization": "Bearer debug-secret"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["path"] == str(log_path)
    assert payload["line_count"] == 2
    assert payload["truncated"] is True
    assert [json.loads(line)["event"] for line in payload["lines"]] == [
        "debug_event_two",
        "debug_event_three",
    ]


def test_admin_debug_log_endpoint_clamps_requested_line_count(monkeypatch, tmp_path):
    log_path = tmp_path / "debug.ndjson"
    log_path.write_text(
        "\n".join(f"line-{index}" for index in range(510)) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CURATOR_DEBUG_LOG_PATH", str(log_path))
    monkeypatch.setenv("CURATOR_DEBUG_LOG_TOKEN", "debug-secret")
    client = _build_client(monkeypatch, tmp_path)

    response = client.get(
        "/debug/logs?lines=999",
        headers={ "X-Debug-Log-Token": "debug-secret" },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["line_count"] == 500
    assert payload["truncated"] is True
    assert payload["lines"][0] == "line-10"
    assert payload["lines"][-1] == "line-509"


def test_admin_debug_log_endpoint_rejects_invalid_line_count(monkeypatch, tmp_path):
    log_path = tmp_path / "debug.ndjson"
    log_path.write_text('{"event":"existing"}\n', encoding="utf-8")
    monkeypatch.setenv("CURATOR_DEBUG_LOG_PATH", str(log_path))
    monkeypatch.setenv("CURATOR_DEBUG_LOG_TOKEN", "debug-secret")
    client = _build_client(monkeypatch, tmp_path)

    response = client.get(
        "/debug/logs?lines=zero",
        headers={"Authorization": "Bearer debug-secret"},
    )

    assert response.status_code == 400
    assert "lines must be an integer" in response.get_json()["error"]


def test_admin_debug_log_endpoint_handles_missing_and_invalid_path(monkeypatch, tmp_path):
    monkeypatch.setenv("CURATOR_DEBUG_LOG_TOKEN", "debug-secret")
    client = _build_client(monkeypatch, tmp_path)

    missing_config_response = client.get(
        "/debug/logs",
        headers={"Authorization": "Bearer debug-secret"},
    )
    assert missing_config_response.status_code == 503
    assert missing_config_response.get_json()["error"] == "Debug log endpoint is not configured."

    monkeypatch.setenv("CURATOR_DEBUG_LOG_PATH", "relative/debug.ndjson")
    invalid_path_response = client.get(
        "/debug/logs",
        headers={"Authorization": "Bearer debug-secret"},
    )
    assert invalid_path_response.status_code == 503
    assert invalid_path_response.get_json()["error"] == "Debug log path is invalid."

    monkeypatch.setenv("CURATOR_DEBUG_LOG_PATH", str(tmp_path / "missing.ndjson"))
    missing_file_response = client.get(
        "/debug/logs",
        headers={"Authorization": "Bearer debug-secret"},
    )
    assert missing_file_response.status_code == 404
    assert missing_file_response.get_json()["error"] == "Debug log file was not found."


def test_admin_debug_log_endpoint_rejects_symlink_path(monkeypatch, tmp_path):
    log_path = tmp_path / "debug.ndjson"
    link_path = tmp_path / "debug-link.ndjson"
    log_path.write_text('{"event":"existing"}\n', encoding="utf-8")
    link_path.symlink_to(log_path)
    monkeypatch.setenv("CURATOR_DEBUG_LOG_PATH", str(link_path))
    monkeypatch.setenv("CURATOR_DEBUG_LOG_TOKEN", "debug-secret")
    client = _build_client(monkeypatch, tmp_path)

    response = client.get(
        "/debug/logs",
        headers={"Authorization": "Bearer debug-secret"},
    )

    assert response.status_code == 503
    assert response.get_json()["error"] == "Debug log path is invalid."
