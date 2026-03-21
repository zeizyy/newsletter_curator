from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess

from .config import BASE_DIR
from .content import trim_context
from .repository import SQLiteRepository


def collect_additional_source_links(config: dict, *, base_dir: str | os.PathLike[str] | None = None) -> list[dict]:
    source_cfg = config.get("additional_sources", {})
    if not source_cfg.get("enabled", False):
        return []

    root_dir = Path(base_dir or BASE_DIR)
    script_path = source_cfg.get(
        "script_path", "skills/daily-news-curator/scripts/build_daily_digest.py"
    )
    if not os.path.isabs(script_path):
        script_path = str(root_dir / script_path)
    if not os.path.exists(script_path):
        print(f"Additional sources script not found: {script_path}")
        return []

    command = [
        "python3",
        script_path,
        "--output",
        "json",
        "--hours",
        str(source_cfg.get("hours", 24)),
        "--top-per-category",
        str(source_cfg.get("top_per_category", 5)),
        "--max-total",
        str(source_cfg.get("max_total", 20)),
    ]

    feeds_file = source_cfg.get("feeds_file", "")
    if feeds_file:
        if not os.path.isabs(feeds_file):
            feeds_file = str(root_dir / feeds_file)
        command.extend(["--feeds-file", feeds_file])

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print("Additional source ingestion failed.")
        if result.stderr.strip():
            print(result.stderr.strip())
        return []

    output = result.stdout.strip()
    if not output:
        return []

    try:
        stories = json.loads(output)
    except json.JSONDecodeError:
        print("Additional source ingestion returned non-JSON output.")
        return []

    if not isinstance(stories, list):
        print("Additional source ingestion output was not a list.")
        return []

    links = []
    for story in stories:
        if not isinstance(story, dict):
            continue
        url = str(story.get("url", "")).strip()
        if not url:
            continue
        title = str(story.get("title", "")).strip()
        source = str(story.get("source", "")).strip() or "Additional Source"
        category = str(story.get("category", "")).strip()
        published_at = str(story.get("published_at", "")).strip()
        summary = str(story.get("summary", "")).strip()
        context = trim_context(summary or title or url)
        links.append(
            {
                "subject": f"[{category or 'general'}] {title or source}",
                "from": source,
                "source_name": source,
                "source_type": "additional_source",
                "date": published_at,
                "url": url,
                "anchor_text": title or source,
                "context": context,
            }
        )
    return links


def load_canned_source_links(
    config: dict,
    *,
    base_dir: str | os.PathLike[str] | None = None,
) -> list[dict]:
    development_cfg = config.get("development", {})
    canned_file = development_cfg.get("canned_sources_file", "tests/fixtures/canned_sources.json")
    root_dir = Path(base_dir or BASE_DIR)
    canned_path = Path(canned_file)
    if not canned_path.is_absolute():
        canned_path = root_dir / canned_path
    with canned_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("canned sources file must contain a JSON list")
    return [dict(item) for item in data if isinstance(item, dict)]


def collect_repository_source_links(
    config: dict,
    *,
    repository: SQLiteRepository | None = None,
    base_dir: str | os.PathLike[str] | None = None,
) -> list[dict]:
    source_cfg = config.get("additional_sources", {})
    if not source_cfg.get("enabled", False):
        return []

    database_path = config.get("database", {}).get("path", "data/newsletter_curator.sqlite3")
    root_dir = Path(base_dir or BASE_DIR)
    if not Path(database_path).is_absolute():
        database_path = root_dir / database_path

    repository = repository or SQLiteRepository(Path(database_path))
    repository.initialize()

    cutoff = datetime.now(UTC) - timedelta(hours=int(source_cfg.get("hours", 24)))
    stories = repository.list_stories(
        source_type="additional_source",
        published_after=cutoff.isoformat(),
    )
    enabled_map = {
        (row["source_type"], row["source_name"]): row["enabled"]
        for row in repository.list_enabled_sources()
    }
    links = []
    for story in stories:
        if not enabled_map.get((story["source_type"], story["source_name"]), True):
            continue
        title = str(story.get("anchor_text", "")).strip() or str(story.get("subject", "")).strip()
        source_name = str(story.get("source_name", "")).strip() or "Additional Source"
        category = str(story.get("category", "")).strip()
        summary = str(story.get("summary", "")).strip()
        context = trim_context(story.get("context") or summary or title or story.get("url", ""))
        links.append(
            {
                "subject": str(story.get("subject", "")).strip() or f"[{category or 'general'}] {title or source_name}",
                "from": source_name,
                "source_name": source_name,
                "source_type": "additional_source",
                "date": str(story.get("published_at", "")).strip(),
                "url": str(story.get("url", "")).strip(),
                "anchor_text": title or source_name,
                "context": context,
                "category": category,
                "summary": summary,
                "article_text": str(story.get("article_text", "") or ""),
            }
        )
    return links
