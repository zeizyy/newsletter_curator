from __future__ import annotations

from curator.content import ACCESS_CLASSIFIER_VERSION
from curator.evaluation import export_evaluation_candidates, store_agent_evaluation
from curator.jobs import get_repository_from_config
from tests.helpers import write_temp_config


def test_agent_evaluation_writes_labels(tmp_path):
    from curator.config import load_config

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    config = load_config(str(config_path))
    repository = get_repository_from_config(config)

    servable_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Open Wire",
            "subject": "[markets] Public article",
            "url": "https://example.com/markets/public-article",
            "anchor_text": "Public article",
            "context": "Public article context",
            "category": "Markets / stocks / macro / economy",
            "published_at": "2026-03-21T07:30:00+00:00",
        }
    )
    repository.upsert_article_snapshot(
        servable_story_id,
        "Public article text with enough depth to be servable.",
        servability_status="servable",
        detector_version=ACCESS_CLASSIFIER_VERSION,
        classifier_signals={"word_count": 9},
        summary_headline="Public article",
        summary_body="Key takeaways\n- Public article remains servable.",
        summary_model="gpt-5-mini",
        summarized_at="2026-03-21T07:35:00+00:00",
    )

    blocked_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Locked Wire",
            "subject": "[media] Subscriber wall",
            "url": "https://example.com/media/subscriber-wall",
            "anchor_text": "Subscriber wall",
            "context": "Subscriber wall context",
            "category": "Tech blogs",
            "published_at": "2026-03-21T06:30:00+00:00",
        }
    )
    repository.upsert_article_snapshot(
        blocked_story_id,
        "Subscribe to continue reading. Already a subscriber? Sign in to continue reading.",
        paywall_detected=True,
        paywall_reason="subscribe_to_continue",
        servability_status="blocked",
        detector_version=ACCESS_CLASSIFIER_VERSION,
        classifier_signals={"strong_text_markers": ["subscribe_to_continue"]},
    )

    candidates = export_evaluation_candidates(repository, limit=10)
    by_url = {candidate["url"]: candidate for candidate in candidates}
    assert by_url["https://example.com/markets/public-article"]["servability_status"] == "servable"
    assert by_url["https://example.com/media/subscriber-wall"]["servability_status"] == "blocked"

    result = store_agent_evaluation(
        repository,
        evaluator="codex",
        scope={"source_type": "additional_source", "limit": 10},
        labels=[
            {
                "story_id": servable_story_id,
                "classifier_status": "servable",
                "agent_label": "servable",
                "rationale": "Full article text and a complete summary are present.",
            },
            {
                "story_id": blocked_story_id,
                "classifier_status": "blocked",
                "agent_label": "blocked",
                "rationale": "The article is clearly behind a subscriber wall.",
            },
        ],
    )

    counts = repository.get_table_counts()
    runs = repository.list_access_evaluation_runs()
    labels = repository.list_access_evaluation_labels(result["evaluation_run_id"])

    assert result["status"] == "completed"
    assert result["counts"] == {"servable": 1, "blocked": 1, "uncertain": 0}
    assert counts["access_evaluation_runs"] == 1
    assert counts["access_evaluation_labels"] == 2
    assert runs[0]["evaluator"] == "codex"
    assert runs[0]["metadata"]["counts"] == {"servable": 1, "blocked": 1, "uncertain": 0}
    assert {label["agent_label"] for label in labels} == {"servable", "blocked"}
