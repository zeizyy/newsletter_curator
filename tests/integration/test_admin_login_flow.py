from __future__ import annotations

import importlib

from tests.helpers import write_temp_config


def test_admin_login_sets_cookie_and_removes_url_token_flow(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CURATOR_ADMIN_TOKEN", "ops-secret")

    client = admin_app.app.test_client()

    redirect_response = client.get("/")
    assert redirect_response.status_code == 302
    assert redirect_response.headers["Location"].startswith("/admin/login?next=")

    login_page_response = client.get("/admin/login")
    login_page = login_page_response.get_data(as_text=True)
    assert login_page_response.status_code == 200
    assert "Sign in to the control room" in login_page
    assert "?token=" not in login_page

    invalid_response = client.post("/admin/login", data={"admin_token": "wrong-token"})
    invalid_page = invalid_response.get_data(as_text=True)
    assert invalid_response.status_code == 200
    assert "admin token is invalid" in invalid_page.lower()

    login_response = client.post(
        "/admin/login",
        data={"admin_token": "ops-secret", "next": "/analytics"},
    )
    assert login_response.status_code == 302
    assert login_response.headers["Location"] == "/analytics"
    assert "curator_admin_token=" in login_response.headers.get("Set-Cookie", "")

    analytics_response = client.get("/analytics")
    analytics_page = analytics_response.get_data(as_text=True)
    assert analytics_response.status_code == 200
    assert "Insight Ledger" in analytics_page

    header_response = client.get("/newsletters", headers={"X-Admin-Token": "ops-secret"})
    assert header_response.status_code == 200

    logout_response = client.post("/admin/logout", follow_redirects=True)
    logout_page = logout_response.get_data(as_text=True)
    assert logout_response.status_code == 200
    assert "You have been signed out." in logout_page

    after_logout_response = client.get("/")
    assert after_logout_response.status_code == 302
    assert after_logout_response.headers["Location"].startswith("/admin/login?next=")


def test_admin_login_marks_cookie_secure_when_proxy_headers_are_trusted(monkeypatch, tmp_path):
    monkeypatch.setenv("CURATOR_TRUST_PROXY_HEADERS", "1")
    admin_app = importlib.reload(importlib.import_module("admin_app"))

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CURATOR_ADMIN_TOKEN", "ops-secret")

    client = admin_app.app.test_client()
    response = client.post(
        "/admin/login",
        data={"admin_token": "ops-secret"},
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "curator.example.com"},
    )

    assert response.status_code == 302
    assert "Secure;" in response.headers.get("Set-Cookie", "")
