from __future__ import annotations

import importlib
import threading

from curator.jobs import current_newsletter_date, get_repository_from_config
from tests.helpers import write_temp_config


def test_preview_generation_lock_prevents_duplicate_runs(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {"digest_recipients": ["preview@example.com"]},
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    config = main.load_config()
    repository = get_repository_from_config(config)

    started = threading.Event()
    release = threading.Event()
    call_lock = threading.Lock()
    call_count = {"value": 0}
    first_response: dict[str, object] = {}

    def fake_preview_job(_config: dict):
        with call_lock:
            call_count["value"] += 1
        started.set()
        assert release.wait(timeout=5), "preview generation did not release in time"
        return {
            "preview": {
                "subject": "Daily Newsletter Digest",
                "body": "Preview body",
                "html_body": "<html><body>Preview body</body></html>",
            },
            "ranked_candidates": 1,
            "selected": 1,
            "accepted_items": 1,
        }

    monkeypatch.setattr(admin_app, "preview_job", fake_preview_job)

    def run_first_request():
        client = admin_app.app.test_client()
        response = client.get("/preview")
        first_response["status_code"] = response.status_code
        first_response["body"] = response.get_data(as_text=True)

    thread = threading.Thread(target=run_first_request)
    thread.start()
    assert started.wait(timeout=5), "first preview request did not start"

    second_client = admin_app.app.test_client()
    second_response = second_client.get("/preview")
    second_html = second_response.get_data(as_text=True)

    assert second_response.status_code == 202
    assert "generation is already in progress" in second_html.lower()
    assert call_count["value"] == 1

    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive(), "first preview request did not finish"

    assert first_response["status_code"] == 202
    assert "generation has started" in str(first_response["body"]).lower()
    assert call_count["value"] == 1

    for _ in range(20):
        generation = repository.get_preview_generation(current_newsletter_date())
        if generation is not None and generation["status"] == "completed":
            break
    assert generation is not None
    assert generation["status"] == "completed"
