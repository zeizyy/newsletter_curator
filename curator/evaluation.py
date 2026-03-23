from __future__ import annotations

import json
from pathlib import Path

from .repository import SQLiteRepository


def export_evaluation_candidates(
    repository: SQLiteRepository,
    *,
    limit: int = 50,
    source_type: str | None = None,
) -> list[dict]:
    stories = repository.list_stories(source_type=source_type)
    candidates: list[dict] = []
    for story in stories[:limit]:
        candidates.append(
            {
                "story_id": int(story["id"]),
                "url": str(story.get("url", "")),
                "source_type": str(story.get("source_type", "")),
                "source_name": str(story.get("source_name", "")),
                "title": str(story.get("anchor_text", "") or story.get("subject", "")),
                "context": str(story.get("context", "")),
                "category": str(story.get("category", "")),
                "published_at": str(story.get("published_at", "")),
                "servability_status": str(story.get("servability_status", "")),
                "paywall_reason": str(story.get("paywall_reason", "")),
                "detector_version": str(story.get("detector_version", "")),
                "classifier_signals": story.get("classifier_signals", {}) or {},
                "article_text": str(story.get("article_text", "")),
                "summary_body": str(story.get("summary_body", "")),
            }
        )
    return candidates


def store_agent_evaluation(
    repository: SQLiteRepository,
    *,
    labels: list[dict],
    evaluator: str = "codex",
    scope: dict | None = None,
) -> dict:
    run_id = repository.create_access_evaluation_run(
        evaluator,
        scope=scope or {"label_count": len(labels)},
    )
    counts = {"servable": 0, "blocked": 0, "uncertain": 0}
    for label in labels:
        agent_label = str(label.get("agent_label", "")).strip().lower()
        if agent_label not in counts:
            raise ValueError(f"Unsupported agent_label: {agent_label}")
        counts[agent_label] += 1
        repository.record_access_evaluation_label(
            run_id,
            story_id=int(label["story_id"]),
            classifier_status=str(label.get("classifier_status", "")).strip(),
            agent_label=agent_label,
            rationale=str(label.get("rationale", "")).strip(),
        )
    repository.complete_access_evaluation_run(
        run_id,
        status="completed",
        metadata={"counts": counts, "labels_written": len(labels)},
    )
    return {
        "evaluation_run_id": run_id,
        "status": "completed",
        "counts": counts,
        "labels_written": len(labels),
    }


def load_labels_file(path: str | Path) -> list[dict]:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, list):
        raise ValueError("Labels file must contain a JSON array.")
    return [dict(item) for item in payload]
