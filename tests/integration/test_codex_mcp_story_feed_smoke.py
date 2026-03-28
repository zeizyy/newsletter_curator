from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from curator import config as config_module
from curator.jobs import get_repository_from_config
from tests.helpers import create_completed_ingestion_run, write_temp_config


def _set_story_first_seen(repository, story_id: int, timestamp: str) -> None:
    with repository.connect() as connection:
        connection.execute(
            """
            UPDATE fetched_stories
            SET first_seen_at = ?, last_seen_at = ?
            WHERE id = ?
            """,
            (timestamp, timestamp, story_id),
        )


def test_codex_mcp_story_feed_skill_workflow(tmp_path, repo_root):
    skill_path = repo_root / "skills" / "codex-mcp-story-feed" / "SKILL.md"
    skill_text = skill_path.read_text(encoding="utf-8")
    assert "$codex-mcp-story-feed" in skill_text
    assert "plugins/newsletter-curator-story-feed" in skill_text
    assert "list_recent_stories" in skill_text

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    config = config_module.load_config(str(config_path))
    repository = get_repository_from_config(config)
    run_id = create_completed_ingestion_run(repository, "gmail")

    now = datetime.now(UTC)
    recent = (now - timedelta(minutes=20)).isoformat()
    older = (now - timedelta(hours=3)).isoformat()

    recent_story_id = repository.upsert_story(
        {
            "source_type": "gmail",
            "source_name": "Infra Letter",
            "subject": "Recent Gmail story",
            "url": "https://example.com/gmail/recent",
            "anchor_text": "Recent Gmail story",
            "context": "Recent context",
            "category": "Tech company news & strategy",
            "published_at": recent,
            "summary": "Recent Gmail summary",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        recent_story_id,
        "Recent article text",
        summary_headline="Recent Gmail story",
        summary_body="Recent Gmail summary body.",
        summarized_at=recent,
    )

    older_story_id = repository.upsert_story(
        {
            "source_type": "gmail",
            "source_name": "Infra Letter",
            "subject": "Older Gmail story",
            "url": "https://example.com/gmail/older",
            "anchor_text": "Older Gmail story",
            "context": "Older context",
            "category": "Tech company news & strategy",
            "published_at": older,
            "summary": "Older Gmail summary",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        older_story_id,
        "Older article text",
        summary_headline="Older Gmail story",
        summary_body="Older Gmail summary body.",
        summarized_at=older,
    )
    _set_story_first_seen(repository, older_story_id, older)

    script_path = repo_root / "skills" / "codex-mcp-story-feed" / "scripts" / "query_story_feed.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--config-path",
            str(config_path),
            "--hours",
            "1",
            "--source-type",
            "gmail",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["window_hours"] == 1
    assert payload["story_count"] == 1
    assert [story["id"] for story in payload["stories"]] == [recent_story_id]
    assert payload["stories"][0]["source_type"] == "gmail"
