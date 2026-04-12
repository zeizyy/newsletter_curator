from __future__ import annotations

import importlib
import re

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
    chip_id = repository.upsert_source(source_type="additional_source", source_name="Chip Insider")
    repository.set_source_selection_by_id(macro_id, enabled=True)
    repository.set_source_selection_by_id(ai_id, enabled=False)
    repository.set_source_selection_by_id(signal_id, enabled=True)
    repository.set_source_selection_by_id(chip_id, enabled=True)

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
    assert 'type="search"' in page
    assert 'id="preferred_source_search"' in page
    assert "Your selected sources (2)" in page
    assert "Suggested sources" in page
    assert "const zeroPrefixLimit = 5;" in page
    assert "Show all available sources" in page
    assert "All available sources" in page
    assert "Show fewer sources" in page
    assert "Publisher feeds" not in page
    assert "Gmail newsletters" not in page
    assert "Gmail newsletter" not in page
    assert "Additional feed" not in page
    assert page.count('value="Macro Wire"') == 1
    assert page.count('value="AI Wire"') == 1
    assert page.count('value="Signal Mail"') == 1
    assert page.index("Signal Mail") < page.index("Macro Wire")
    assert page.index("Signal Mail") < page.index("AI Wire")
    assert re.search(r'value="AI Wire"[^>]*checked[^>]*disabled', page)

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
    assert "Catalog defaults are preselected for you." in saved_page

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
    assert "Your selected sources (3)" in second_page
    assert "Suggested sources" in second_page
    assert "Show all available sources" in second_page


def test_subscriber_settings_auto_selects_default_catalog_sources(monkeypatch, tmp_path):
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))

    repository, subscriber, session = _create_logged_in_subscriber(admin_app, "defaults@example.com")
    repository.upsert_source(source_type="additional_source", source_name="OpenAI News")
    repository.upsert_source(source_type="additional_source", source_name="Macro Wire")

    client = admin_app.app.test_client()
    client.set_cookie(admin_app.SUBSCRIBER_SESSION_COOKIE, session["token"])

    response = client.get("/settings")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Your selected sources (1)" in page
    assert re.search(r'value="OpenAI News"[^>]*checked', page)
    assert page.index("OpenAI News") < page.index("Macro Wire")
    profile_after_load = repository.get_subscriber_profile(int(subscriber["id"]))
    assert profile_after_load["preferred_sources"] == ["OpenAI News"]

    save_response = client.post(
        "/settings",
        data={
            "persona_text": "",
            "preferred_source": ["OpenAI News", "Macro Wire"],
        },
        follow_redirects=True,
    )
    saved_page = save_response.get_data(as_text=True)
    assert save_response.status_code == 200
    assert "OpenAI News" in saved_page
    assert "Macro Wire" in saved_page

    profile = repository.get_subscriber_profile(int(subscriber["id"]))
    assert profile["preferred_sources"] == ["OpenAI News", "Macro Wire"]


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
