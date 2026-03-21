from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from .config import BASE_DIR
from .content import trim_context


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
