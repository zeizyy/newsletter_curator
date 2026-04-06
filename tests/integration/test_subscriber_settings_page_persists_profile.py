from __future__ import annotations

import importlib

from tests.helpers import write_temp_config


def _create_logged_in_subscriber(admin_app_module, email_address: str):
    repository = admin_app_module.load_repository(admin_app_module.load_merged_config())
    subscriber = repository.upsert_subscriber(email_address)
    session = repository.create_subscriber_session(int(subscriber["id"]))
    return repository, subscriber, session


def test_subscriber_settings_page_persists_profile(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))

    repository, subscriber, session = _create_logged_in_subscriber(admin_app, "subscriber@example.com")
    repository.upsert_subscriber_profile(
        int(subscriber["id"]),
        persona_text="Existing persona",
        delivery_format="email",
        preferred_sources=["Macro Wire", "AI Wire"],
    )

    macro_id = repository.upsert_source(source_type="additional_source", source_name="Macro Wire")
    ai_id = repository.upsert_source(source_type="additional_source", source_name="AI Wire")
    signal_id = repository.upsert_source(source_type="gmail", source_name="Signal Mail")
    repository.set_source_selection_by_id(macro_id, enabled=True)
    repository.set_source_selection_by_id(ai_id, enabled=False)
    repository.set_source_selection_by_id(signal_id, enabled=True)

    client = admin_app.app.test_client()
    client.set_cookie(admin_app.SUBSCRIBER_SESSION_COOKIE, session["token"])

    response = client.get("/settings")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Existing persona" in page
    assert "Add a PDF copy" in page
    assert "Add PDF attachment" in page
    assert "Subscriber Rail" not in page
    assert "Macro Wire" in page
    assert "AI Wire" in page
    assert "Unavailable" in page
    assert "Publisher feeds" not in page
    assert "Gmail newsletters" not in page

    save_response = client.post(
        "/settings",
        data={
            "persona_text": "  Focus on chips and costs.  ",
            "pdf_delivery_enabled": "1",
            "preferred_source": ["Macro Wire", "Signal Mail"],
        },
        follow_redirects=True,
    )
    saved_page = save_response.get_data(as_text=True)
    assert save_response.status_code == 200
    assert "Subscriber settings saved." in saved_page
    assert "Focus on chips and costs." in saved_page
    assert "Signal Mail" in saved_page
    assert "Preferred sources act as a soft uprank during your personalized final ranking pass." in saved_page

    profile = repository.get_subscriber_profile(int(subscriber["id"]))
    assert profile["persona_text"] == "Focus on chips and costs."
    assert profile["delivery_format"] == "pdf"
    assert profile["preferred_sources"] == ["Macro Wire", "Signal Mail", "AI Wire"]

    second_session = repository.create_subscriber_session(int(subscriber["id"]))
    second_client = admin_app.app.test_client()
    second_client.set_cookie(admin_app.SUBSCRIBER_SESSION_COOKIE, second_session["token"])
    second_response = second_client.get("/settings")
    second_page = second_response.get_data(as_text=True)
    assert second_response.status_code == 200
    assert "Focus on chips and costs." in second_page
    assert 'name="pdf_delivery_enabled"' in second_page
    assert 'value="1"' in second_page
    assert "Signal Mail" in second_page
    assert "AI Wire" in second_page


def test_subscriber_settings_requires_authentication(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))

    client = admin_app.app.test_client()
    response = client.get("/settings")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
