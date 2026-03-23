from __future__ import annotations

from curator.content import ACCESS_CLASSIFIER_VERSION
from curator.evaluation import replay_classifier_against_evaluation, store_agent_evaluation
from curator.jobs import get_repository_from_config
from tests.helpers import write_temp_config


def test_classifier_replay_loop(tmp_path):
    from curator.config import load_config

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    config = load_config(str(config_path))
    repository = get_repository_from_config(config)

    corrected_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Replay Wire",
            "subject": "[replay] js blocked",
            "url": "https://example.com/replay/js-blocked",
            "anchor_text": "JS blocked story",
            "context": "Replay context",
            "category": "Tech blogs",
            "published_at": "2026-03-21T07:30:00+00:00",
        }
    )
    repository.upsert_article_snapshot(
        corrected_story_id,
        "Site content blocked due to JavaScript being disabled. Please enable JavaScript to continue reading this page.",
        servability_status="servable",
        detector_version="older-detector",
        classifier_signals={"word_count": 12},
    )

    stable_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Replay Wire",
            "subject": "[replay] public article",
            "url": "https://example.com/replay/public-article",
            "anchor_text": "Public article",
            "context": "Replay context",
            "category": "Tech blogs",
            "published_at": "2026-03-21T06:30:00+00:00",
        }
    )
    repository.upsert_article_snapshot(
        stable_story_id,
        "Public article text with enough depth to remain servable.",
        servability_status="servable",
        detector_version="older-detector",
        classifier_signals={"word_count": 10},
    )

    evaluation = store_agent_evaluation(
        repository,
        evaluator="codex",
        labels=[
            {
                "story_id": corrected_story_id,
                "classifier_status": "servable",
                "agent_label": "blocked",
                "rationale": "This is clearly a blocked placeholder page.",
            },
            {
                "story_id": stable_story_id,
                "classifier_status": "servable",
                "agent_label": "servable",
                "rationale": "This remains a normal servable article.",
            },
        ],
    )

    replay = replay_classifier_against_evaluation(
        repository,
        evaluation_run_id=evaluation["evaluation_run_id"],
    )

    assert replay["replay_detector_version"] == ACCESS_CLASSIFIER_VERSION
    assert replay["changed_decisions_count"] == 1
    assert replay["changed_decisions"][0]["story_id"] == corrected_story_id
    assert replay["changed_decisions"][0]["previous_classifier_status"] == "servable"
    assert replay["changed_decisions"][0]["replay_classifier_status"] == "blocked"
    assert replay["metrics"] == {
        "labels_reviewed": 2,
        "uncertain_labels": 0,
        "true_positives": 1,
        "false_positives": 0,
        "false_negatives": 0,
        "true_negatives": 1,
        "evaluated_labels": 2,
    }
