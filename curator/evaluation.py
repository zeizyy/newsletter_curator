from __future__ import annotations

import json
from pathlib import Path

from .content import ACCESS_CLASSIFIER_VERSION, classify_article_access
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
    metrics = repository.get_access_evaluation_metrics(run_id)
    repository.complete_access_evaluation_run(
        run_id,
        status="completed",
        metadata={"counts": counts, "labels_written": len(labels), "metrics": metrics},
    )
    return {
        "evaluation_run_id": run_id,
        "status": "completed",
        "counts": counts,
        "metrics": metrics,
        "labels_written": len(labels),
    }


def report_access_evaluations(
    repository: SQLiteRepository,
    *,
    limit: int = 10,
) -> list[dict]:
    return repository.list_access_evaluation_run_summaries(limit=limit)


def _metrics_from_classifier_rows(rows: list[dict]) -> dict[str, int]:
    metrics = {
        "labels_reviewed": len(rows),
        "uncertain_labels": 0,
        "true_positives": 0,
        "false_positives": 0,
        "false_negatives": 0,
        "true_negatives": 0,
        "evaluated_labels": 0,
    }
    for row in rows:
        agent_label = str(row.get("agent_label", "")).strip().lower()
        classifier_status = str(row.get("classifier_status", "")).strip().lower()
        if agent_label == "uncertain":
            metrics["uncertain_labels"] += 1
            continue
        metrics["evaluated_labels"] += 1
        if classifier_status == "blocked" and agent_label == "blocked":
            metrics["true_positives"] += 1
        elif classifier_status == "blocked" and agent_label == "servable":
            metrics["false_positives"] += 1
        elif classifier_status != "blocked" and agent_label == "blocked":
            metrics["false_negatives"] += 1
        elif classifier_status != "blocked" and agent_label == "servable":
            metrics["true_negatives"] += 1
    return metrics


def replay_classifier_against_evaluation(
    repository: SQLiteRepository,
    *,
    evaluation_run_id: int,
) -> dict:
    labels = repository.list_access_evaluation_labels(evaluation_run_id)
    replay_rows: list[dict] = []
    changed: list[dict] = []

    for label in labels:
        story = repository.get_story(int(label["story_id"]))
        if story is None:
            continue
        replay = classify_article_access(
            str(story.get("article_text", "")),
            str(story.get("url", "")),
            document_title=str(story.get("anchor_text", "") or story.get("subject", "")),
            document_excerpt=str(story.get("context", "")),
        )
        replay_status = "blocked" if replay["blocked"] else "servable"
        replay_row = {
            "story_id": int(label["story_id"]),
            "url": str(label.get("url", "")),
            "source_name": str(label.get("source_name", "")),
            "previous_classifier_status": str(label.get("classifier_status", "")),
            "classifier_status": replay_status,
            "agent_label": str(label.get("agent_label", "")),
            "rationale": str(label.get("rationale", "")),
            "replay_reason": str(replay.get("reason", "")),
            "replay_signals": replay.get("signals", {}) or {},
        }
        replay_rows.append(replay_row)
        if replay_status != replay_row["previous_classifier_status"]:
            changed.append(
                {
                    "story_id": replay_row["story_id"],
                    "url": replay_row["url"],
                    "source_name": replay_row["source_name"],
                    "previous_classifier_status": replay_row["previous_classifier_status"],
                    "replay_classifier_status": replay_status,
                    "replay_reason": replay_row["replay_reason"],
                }
            )

    metrics = _metrics_from_classifier_rows(replay_rows)
    return {
        "evaluation_run_id": evaluation_run_id,
        "replay_detector_version": ACCESS_CLASSIFIER_VERSION,
        "metrics": metrics,
        "changed_decisions_count": len(changed),
        "changed_decisions": changed,
    }


def load_labels_file(path: str | Path) -> list[dict]:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, list):
        raise ValueError("Labels file must contain a JSON array.")
    return [dict(item) for item in payload]
