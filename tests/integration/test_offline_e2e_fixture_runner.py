from __future__ import annotations

import json
import subprocess
import sys


def _run_fixture(repo_root, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "run_offline_e2e_fixture.py"),
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_offline_e2e_fixture_runner_smoke_emits_stage_runtime_metrics(repo_root):
    completed = _run_fixture(repo_root, "--scenario", "smoke")

    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)

    assert payload["status"] == "completed"
    assert payload["budget_ok"] is True
    assert payload["repository"]["story_count"] >= 2
    assert len(payload["sent_messages"]) == 1
    assert payload["result"]["runtime"]["elapsed_ms"] >= 0
    assert payload["result"]["runtime"]["max_rss_mb_after"] >= 0
    assert payload["result"]["stages"]["fetch_gmail"]["runtime"]["elapsed_ms"] >= 0
    assert payload["result"]["stages"]["fetch_sources"]["runtime"]["elapsed_ms"] >= 0
    assert payload["result"]["stages"]["deliver_digest"]["runtime"]["elapsed_ms"] >= 0
    assert any(entry.get("event") == "daily_orchestrator" for entry in payload["captured_logs"])


def test_offline_e2e_fixture_runner_main_flow_covers_generation_filtering_summary_and_delivery(
    repo_root,
):
    completed = _run_fixture(repo_root, "--scenario", "main_flow")

    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    result = payload["result"]
    delivery_stage = result["stages"]["deliver_digest"]
    sent_message = payload["sent_messages"][0]

    assert payload["status"] == "completed"
    assert payload["repository"]["story_count"] == 4
    assert result["stages"]["fetch_gmail"]["stories_seen"] == 3
    assert result["stages"]["fetch_gmail"]["stories_persisted"] == 2
    assert result["stages"]["fetch_gmail"]["article_failures"] == 1
    assert delivery_stage["status"] == "completed"
    assert delivery_stage["deduped_links"] == 3
    assert delivery_stage["ranked_candidates"] == 3
    assert delivery_stage["selected"] == 3
    assert delivery_stage["accepted_items"] == 3
    assert delivery_stage["backfilled_count"] == 0
    assert delivery_stage["skipped_count"] == 0
    assert delivery_stage["sent_recipients"] == 1
    assert sent_message["subject"] == "Offline E2E Main Flow Digest"
    assert "Top Gmail story covers product strategy" in sent_message["body_preview"]
    accepted_urls = {item["url"] for item in delivery_stage["accepted_story_items"]}
    assert accepted_urls == {
        "https://example.com/gmail/top-story",
        "https://example.com/gmail/backfill-story",
        "https://example.com/source/selected-story",
    }
    assert "https://example.com/gmail/empty-story" not in accepted_urls

    raw_logs = [entry.get("raw", "") for entry in payload["captured_logs"] if "raw" in entry]
    assert "links_merged_deduped: total=3" in raw_logs
    assert "summaries_completed: total=3 target=3" in raw_logs
    assert "summaries_backfilled: 0" in raw_logs
    assert "summaries_skipped_fetch_or_empty: 0" in raw_logs
    assert "returned_final: total=3" in raw_logs


def test_offline_e2e_fixture_runner_memory_stress_stays_within_budget(repo_root):
    completed = _run_fixture(
        repo_root,
        "--scenario",
        "memory_stress",
        "--max-rss-mb",
        "512",
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)

    assert payload["status"] == "completed"
    assert payload["budget_ok"] is True
    assert payload["max_rss_budget_mb"] == 512
    assert payload["max_rss_mb"] > 0
    assert payload["max_rss_mb"] <= 512
    assert payload["repository"]["story_count"] == 16
    assert payload["result"]["stages"]["deliver_digest"]["sent_recipients"] == 1
