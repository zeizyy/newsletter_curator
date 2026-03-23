from __future__ import annotations

from curator.content import ACCESS_CLASSIFIER_VERSION
from curator.evaluation import report_access_evaluations, store_agent_evaluation
from curator.jobs import get_repository_from_config
from tests.helpers import write_temp_config


def seed_story(repository, *, url: str, servability_status: str, paywall_detected: bool) -> int:
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Eval Wire",
            "subject": f"[eval] {url.rsplit('/', 1)[-1]}",
            "url": url,
            "anchor_text": url.rsplit("/", 1)[-1].replace("-", " ").title(),
            "context": "Evaluation corpus story",
            "category": "Tech blogs",
            "published_at": "2026-03-21T07:30:00+00:00",
        }
    )
    repository.upsert_article_snapshot(
        story_id,
        "Story body for evaluation metrics.",
        paywall_detected=paywall_detected,
        paywall_reason="subscribe_to_continue" if paywall_detected else "",
        servability_status=servability_status,
        detector_version=ACCESS_CLASSIFIER_VERSION,
        classifier_signals={"word_count": 5},
    )
    return story_id


def test_classifier_evaluation_metrics(tmp_path):
    from curator.config import load_config

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    config = load_config(str(config_path))
    repository = get_repository_from_config(config)

    true_positive = seed_story(
        repository,
        url="https://example.com/eval/true-positive",
        servability_status="blocked",
        paywall_detected=True,
    )
    false_positive = seed_story(
        repository,
        url="https://example.com/eval/false-positive",
        servability_status="blocked",
        paywall_detected=True,
    )
    false_negative = seed_story(
        repository,
        url="https://example.com/eval/false-negative",
        servability_status="servable",
        paywall_detected=False,
    )
    true_negative = seed_story(
        repository,
        url="https://example.com/eval/true-negative",
        servability_status="candidate",
        paywall_detected=False,
    )
    uncertain = seed_story(
        repository,
        url="https://example.com/eval/uncertain",
        servability_status="candidate",
        paywall_detected=False,
    )

    result = store_agent_evaluation(
        repository,
        evaluator="codex",
        labels=[
            {
                "story_id": true_positive,
                "classifier_status": "blocked",
                "agent_label": "blocked",
                "rationale": "Correctly blocked.",
            },
            {
                "story_id": false_positive,
                "classifier_status": "blocked",
                "agent_label": "servable",
                "rationale": "This one should have been servable.",
            },
            {
                "story_id": false_negative,
                "classifier_status": "servable",
                "agent_label": "blocked",
                "rationale": "This one should have been blocked.",
            },
            {
                "story_id": true_negative,
                "classifier_status": "candidate",
                "agent_label": "servable",
                "rationale": "Not blocked and should remain servable.",
            },
            {
                "story_id": uncertain,
                "classifier_status": "candidate",
                "agent_label": "uncertain",
                "rationale": "Needs more review.",
            },
        ],
    )

    metrics = repository.get_access_evaluation_metrics(result["evaluation_run_id"])
    report = report_access_evaluations(repository, limit=5)

    assert metrics == {
        "labels_reviewed": 5,
        "uncertain_labels": 1,
        "true_positives": 1,
        "false_positives": 1,
        "false_negatives": 1,
        "true_negatives": 1,
        "evaluated_labels": 4,
    }
    assert result["metrics"] == metrics
    assert report[0]["metrics"] == metrics
    assert report[0]["metadata"]["metrics"] == metrics
