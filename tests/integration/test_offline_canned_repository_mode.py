from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib
import json

from curator.jobs import get_repository_from_config, run_fetch_sources_job
from tests.fakes import FakeGmailService
from tests.helpers import write_temp_config


def test_offline_canned_repository_mode(monkeypatch, repo_root, tmp_path):
    main = importlib.import_module("main")
    canned_sources = json.loads(
        (repo_root / "tests" / "fixtures" / "canned_sources.json").read_text(encoding="utf-8")
    )
    now_utc = datetime.now(UTC)
    for index, story in enumerate(canned_sources):
        published_at = (now_utc - timedelta(hours=index + 1)).isoformat()
        story["date"] = published_at
        story["published_at"] = published_at
    canned_sources_path = tmp_path / "canned_sources.json"
    canned_sources_path.write_text(json.dumps(canned_sources), encoding="utf-8")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {
                "use_canned_sources": True,
                "canned_sources_file": str(canned_sources_path),
                "fake_inference": True,
            },
            "email": {
                "digest_recipients": ["offline@example.com"],
                "digest_subject": "Offline Canned Digest",
            },
            "additional_sources": {"enabled": True, "hours": 48},
            "limits": {
                "select_top_stories": 2,
                "final_top_stories": 2,
                "source_quotas": {"gmail": 0, "additional_source": 2},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    def fail_live_article_fetch(*args, **kwargs):
        raise AssertionError("Development canned mode should not fetch article text live.")

    sent_messages: list[dict] = []

    def fake_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        sent_messages.append(
            {
                "to": to_address,
                "subject": subject,
                "body": body,
                "html_body": html_body or "",
            }
        )

    monkeypatch.setattr(main, "fetch_article_text", fail_live_article_fetch)
    monkeypatch.setattr(main, "send_email", fake_send_email)

    fetch_result = run_fetch_sources_job(config)
    repository = get_repository_from_config(config)
    counts = repository.get_table_counts()
    service = FakeGmailService(messages=[])

    main.run_job(config, service, issue_type_override="daily")

    assert fetch_result["status"] == "completed"
    assert counts["fetched_stories"] == 2
    assert counts["article_snapshots"] == 2
    assert len(sent_messages) == 1
    payload = sent_messages[0]
    assert payload["subject"] == "Offline Canned Digest"
    assert "development can run fully offline" in payload["body"]
    assert "Rates reset changes software valuations" in payload["body"]
    assert "Open model pricing changed" in payload["body"]
