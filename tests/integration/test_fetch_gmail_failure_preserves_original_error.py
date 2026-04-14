from __future__ import annotations

import pytest

from curator.config import load_config
from curator.jobs import get_repository_from_config, run_fetch_gmail_job
from tests.fakes import FakeGmailService
from tests.helpers import write_temp_config


def test_fetch_gmail_failure_preserves_original_error_before_fetch_selection(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
        },
    )
    config = load_config(str(config_path))
    repository = get_repository_from_config(config)

    def fail_collect_gmail_links(service, config):
        raise RuntimeError("gmail token refresh failed")

    with pytest.raises(RuntimeError, match="gmail token refresh failed"):
        run_fetch_gmail_job(
            config,
            FakeGmailService(messages=[]),
            collect_gmail_links_fn=fail_collect_gmail_links,
        )

    latest_run = repository.list_recent_ingestion_runs(source_type="gmail", limit=1)[0]

    assert latest_run["status"] == "failed"
    assert latest_run["metadata"]["stories_selected_for_fetch"] == 0
    assert latest_run["metadata"]["failures"] == [{"reason": "gmail token refresh failed"}]
