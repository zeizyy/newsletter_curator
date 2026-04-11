from __future__ import annotations

import importlib
from urllib.parse import parse_qs, urlparse

from curator.jobs import get_repository_from_config
from tests.helpers import write_temp_config


def _repository_for_admin(admin_app_module):
    return admin_app_module.load_repository(admin_app_module.load_merged_config())


def test_subscriber_login_attempts_email_delivery_and_hashes_token(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {"digest_recipients": ["reader@example.com"]},
        },
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CURATOR_PUBLIC_BASE_URL", "http://localhost:8080")

    deliveries: list[dict] = []

    def fake_send_login_email(config: dict, to_address: str, confirm_url: str) -> dict:
        deliveries.append(
            {
                "to_address": to_address,
                "confirm_url": confirm_url,
            }
        )
        return {"sent": True, "error": ""}

    monkeypatch.setattr(admin_app, "send_subscriber_login_email", fake_send_login_email)

    client = admin_app.app.test_client()
    response = client.post(
        "/login",
        data={"email_address": " Reader@Example.com "},
    )
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Sign-in link sent to reader@example.com." in page
    assert "/login/confirm?token=" not in page
    assert len(deliveries) == 1
    assert deliveries[0]["to_address"] == "reader@example.com"
    assert deliveries[0]["confirm_url"].startswith("http://localhost:8080/login/confirm?token=")

    repository = _repository_for_admin(admin_app)
    parsed = urlparse(deliveries[0]["confirm_url"])
    raw_token = parse_qs(parsed.query)["token"][0]
    subscriber = repository.get_subscriber_by_email("reader@example.com")
    assert subscriber is not None

    with repository.connect() as connection:
        subscriber_row = connection.execute(
            "SELECT COUNT(*) AS count FROM subscribers WHERE email_address = ?",
            ("reader@example.com",),
        ).fetchone()
        token_row = connection.execute(
            """
            SELECT token_hash, consumed_at
            FROM subscriber_login_tokens
            WHERE subscriber_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(subscriber["id"]),),
        ).fetchone()

    assert int(subscriber_row["count"]) == 1
    assert token_row is not None
    assert token_row["token_hash"] != raw_token
    assert raw_token not in str(token_row["token_hash"])
    assert token_row["consumed_at"] is None


def test_subscriber_login_and_session_flow(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {"digest_recipients": ["subscriber@example.com"]},
        },
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CURATOR_EXPOSE_LOGIN_LINKS", "1")
    monkeypatch.setenv("CURATOR_ADMIN_TOKEN", "ops-secret")
    monkeypatch.setenv("CURATOR_PUBLIC_BASE_URL", "http://localhost:8080")

    def fake_send_login_email(config: dict, to_address: str, confirm_url: str) -> dict:
        return {"sent": False, "error": "gmail unavailable"}

    monkeypatch.setattr(admin_app, "send_subscriber_login_email", fake_send_login_email)

    client = admin_app.app.test_client()
    login_response = client.post(
        "/login",
        data={"email_address": "subscriber@example.com"},
    )
    login_page = login_response.get_data(as_text=True)

    assert login_response.status_code == 200
    assert "temporary sign-in link" in login_page.lower()
    marker = "http://localhost:8080/login/confirm?token="
    token_start = login_page.index(marker)
    token_end = login_page.index("</pre>", token_start)
    confirm_url = login_page[token_start:token_end].strip()
    confirm_path = urlparse(confirm_url).path + "?" + urlparse(confirm_url).query

    confirm_response = client.get(confirm_path)
    assert confirm_response.status_code == 302
    assert confirm_response.headers["Location"].endswith("/settings")
    assert "curator_subscriber_session=" in confirm_response.headers.get("Set-Cookie", "")

    settings_response = client.get("/settings")
    settings_page = settings_response.get_data(as_text=True)
    assert settings_response.status_code == 200
    assert "Your digest settings" in settings_page
    assert "name=\"persona_text\"" in settings_page

    admin_response = client.get("/")
    assert admin_response.status_code == 302
    assert admin_response.headers["Location"].startswith("/admin/login?next=")

    logout_response = client.post("/logout", follow_redirects=True)
    logout_page = logout_response.get_data(as_text=True)
    assert logout_response.status_code == 200
    assert "You have been signed out." in logout_page

    redirect_response = client.get("/account")
    assert redirect_response.status_code == 302
    assert redirect_response.headers["Location"].endswith("/settings")

    reused_response = client.get(confirm_path)
    reused_page = reused_response.get_data(as_text=True)
    assert reused_response.status_code == 400
    assert "invalid or has expired" in reused_page.lower()

    repository = _repository_for_admin(admin_app)
    subscriber = repository.get_subscriber_by_email("subscriber@example.com")
    assert subscriber is not None
    with repository.connect() as connection:
        session_row = connection.execute(
            """
            SELECT session_token_hash, revoked_at
            FROM subscriber_sessions
            WHERE subscriber_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(subscriber["id"]),),
        ).fetchone()
        token_row = connection.execute(
            """
            SELECT consumed_at
            FROM subscriber_login_tokens
            WHERE subscriber_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(subscriber["id"]),),
        ).fetchone()

    assert session_row is not None
    assert session_row["revoked_at"]
    assert "localhost" not in str(session_row["session_token_hash"])
    assert token_row is not None
    assert token_row["consumed_at"]


def test_subscriber_login_falls_back_to_request_host_and_port_when_public_base_url_is_unset(
    monkeypatch,
    tmp_path,
):
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {"digest_recipients": ["reader@example.com"]},
        },
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    monkeypatch.delenv("CURATOR_PUBLIC_BASE_URL", raising=False)

    deliveries: list[dict] = []

    def fake_send_login_email(config: dict, to_address: str, confirm_url: str) -> dict:
        deliveries.append(confirm_url)
        return {"sent": True, "error": ""}

    monkeypatch.setattr(admin_app, "send_subscriber_login_email", fake_send_login_email)

    client = admin_app.app.test_client()
    response = client.post(
        "/login",
        data={"email_address": "reader@example.com"},
        base_url="http://localhost:8080",
    )

    assert response.status_code == 200
    assert len(deliveries) == 1
    assert deliveries[0].startswith("http://localhost:8080/login/confirm?token=")


def test_subscriber_login_redirects_unregistered_email_to_buttondown_signup(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {"digest_recipients": ["registered@example.com"]},
        },
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))

    client = admin_app.app.test_client()
    response = client.post(
        "/login",
        data={"email_address": "new-reader@example.com"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "https://buttondown.com/zeizyynewsletter"

    repository = _repository_for_admin(admin_app)
    assert repository.get_subscriber_by_email("new-reader@example.com") is None
