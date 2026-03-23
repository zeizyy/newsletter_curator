from __future__ import annotations

import json
from pathlib import Path

from openai import OpenAI

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


def _parse_label_items(text: str) -> list[dict]:
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass

    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except json.JSONDecodeError:
            return []
    return []


def _build_codex_review_prompts(batch: list[dict]) -> tuple[str, str]:
    system_prompt = (
        "You are evaluating whether fetched web articles should be treated as servable content "
        "for a news digest. Decide whether each item is servable, blocked, or uncertain. "
        "Use the article text, title, context, current classifier status, paywall reason, and "
        "classifier signals. Do not blindly trust the current classifier status."
    )
    batch_lines = []
    for item in batch:
        batch_lines.append(
            "\n".join(
                [
                    f"story_id: {item['story_id']}",
                    f"url: {item.get('url', '')}",
                    f"source_name: {item.get('source_name', '')}",
                    f"title: {item.get('title', '')}",
                    f"context: {item.get('context', '')}",
                    f"category: {item.get('category', '')}",
                    f"classifier_status: {item.get('servability_status', '')}",
                    f"paywall_reason: {item.get('paywall_reason', '')}",
                    f"classifier_signals: {json.dumps(item.get('classifier_signals', {}), sort_keys=True)}",
                    f"article_text: {item.get('article_text', '')}",
                ]
            )
        )
    user_prompt = (
        "Review the following fetched story candidates.\n"
        "Return ONLY a JSON array. Each object must be: "
        '{"story_id": <int>, "classifier_status": <string>, "agent_label": <"servable"|"blocked"|"uncertain">, "rationale": <string>}.\n'
        "Preserve the input story_id values exactly.\n\n"
        + "\n\n---\n\n".join(batch_lines)
    )
    return system_prompt, user_prompt


def run_codex_evaluation(
    repository: SQLiteRepository,
    config: dict,
    *,
    evaluator: str = "codex",
    source_type: str | None = None,
    limit: int = 50,
    batch_size: int = 10,
    model: str | None = None,
    client_factory=OpenAI,
) -> dict:
    candidates = export_evaluation_candidates(
        repository,
        limit=limit,
        source_type=source_type,
    )
    if not candidates:
        return {
            "evaluation_run_id": 0,
            "status": "completed",
            "counts": {"servable": 0, "blocked": 0, "uncertain": 0},
            "metrics": {
                "labels_reviewed": 0,
                "uncertain_labels": 0,
                "true_positives": 0,
                "false_positives": 0,
                "false_negatives": 0,
                "true_negatives": 0,
                "evaluated_labels": 0,
            },
            "labels_written": 0,
            "candidate_count": 0,
            "review_model": model or config["openai"]["reasoning_model"],
        }

    review_model = model or config["openai"]["reasoning_model"]
    client = client_factory()
    labels: list[dict] = []
    normalized_candidates = {int(item["story_id"]): item for item in candidates}

    for offset in range(0, len(candidates), max(1, batch_size)):
        batch = candidates[offset : offset + max(1, batch_size)]
        system_prompt, user_prompt = _build_codex_review_prompts(batch)
        response = client.chat.completions.create(
            model=review_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        items = _parse_label_items(response.choices[0].message.content.strip())
        for item in items:
            story_id = item.get("story_id")
            if isinstance(story_id, (int, float)) and int(story_id) == story_id:
                story_id = int(story_id)
            if not isinstance(story_id, int) or story_id not in normalized_candidates:
                continue
            agent_label = str(item.get("agent_label", "")).strip().lower()
            if agent_label not in {"servable", "blocked", "uncertain"}:
                continue
            candidate = normalized_candidates[story_id]
            labels.append(
                {
                    "story_id": story_id,
                    "classifier_status": str(
                        item.get("classifier_status", candidate.get("servability_status", ""))
                    ).strip()
                    or str(candidate.get("servability_status", "")),
                    "agent_label": agent_label,
                    "rationale": str(item.get("rationale", "")).strip(),
                }
            )

    deduped_labels: list[dict] = []
    seen_story_ids: set[int] = set()
    for label in labels:
        story_id = int(label["story_id"])
        if story_id in seen_story_ids:
            continue
        seen_story_ids.add(story_id)
        deduped_labels.append(label)

    result = store_agent_evaluation(
        repository,
        labels=deduped_labels,
        evaluator=evaluator,
        scope={
            "source_type": source_type,
            "limit": limit,
            "batch_size": batch_size,
            "candidate_count": len(candidates),
            "review_model": review_model,
        },
    )
    result["candidate_count"] = len(candidates)
    result["review_model"] = review_model
    return result


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
