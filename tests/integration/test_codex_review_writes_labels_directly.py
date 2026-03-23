from __future__ import annotations

import json
from types import SimpleNamespace

from curator.content import ACCESS_CLASSIFIER_VERSION
from curator.evaluation import run_codex_evaluation
from curator.jobs import get_repository_from_config
from tests.helpers import write_temp_config


class ReviewOpenAI:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, *, model: str, messages: list[dict]):
        user_message = next(message["content"] for message in messages if message["role"] == "user")
        story_ids = []
        for line in user_message.splitlines():
            if line.startswith("story_id:"):
                story_ids.append(int(line.split(":", 1)[1].strip()))

        payload = []
        for story_id in story_ids:
            if story_id % 2 == 0:
                payload.append(
                    {
                        "story_id": story_id,
                        "classifier_status": "blocked",
                        "agent_label": "blocked",
                        "rationale": "Clearly blocked content.",
                    }
                )
            else:
                payload.append(
                    {
                        "story_id": story_id,
                        "classifier_status": "servable",
                        "agent_label": "servable",
                        "rationale": "Looks like servable content.",
                    }
                )
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
            usage=usage,
        )


def test_codex_review_writes_labels_directly(tmp_path):
    from curator.config import load_config

    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    config = load_config(str(config_path))
    repository = get_repository_from_config(config)

    for idx in range(1, 4):
        story_id = repository.upsert_story(
            {
                "source_type": "additional_source",
                "source_name": "Eval Wire",
                "subject": f"[eval] story-{idx}",
                "url": f"https://example.com/eval/story-{idx}",
                "anchor_text": f"Story {idx}",
                "context": f"Context for story {idx}",
                "category": "Tech blogs",
                "published_at": "2026-03-21T07:30:00+00:00",
            }
        )
        repository.upsert_article_snapshot(
            story_id,
            f"Article text for story {idx}.",
            servability_status="candidate",
            detector_version=ACCESS_CLASSIFIER_VERSION,
            classifier_signals={"word_count": 4},
        )

    result = run_codex_evaluation(
        repository,
        config,
        evaluator="codex-auto",
        limit=3,
        batch_size=2,
        client_factory=ReviewOpenAI,
    )

    labels = repository.list_access_evaluation_labels(result["evaluation_run_id"])

    assert result["status"] == "completed"
    assert result["candidate_count"] == 3
    assert result["labels_written"] == 3
    assert result["counts"] == {"servable": 2, "blocked": 1, "uncertain": 0}
    assert {label["agent_label"] for label in labels} == {"servable", "blocked"}
