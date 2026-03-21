from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

from curator.jobs import get_repository_from_config
from tests.fakes import FakeGmailService
from tests.helpers import create_completed_ingestion_run, write_temp_config


class PersonaAwareOpenAI:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, *, model: str, messages: list[dict]):
        prompt_text = "\n".join(message["content"] for message in messages)
        lowered = prompt_text.lower()

        if "select the top stories" in lowered:
            if "macro investor focused on rates and valuations" in lowered:
                content = json.dumps(
                    [
                        {
                            "index": 1,
                            "category": "Markets / stocks / macro / economy",
                            "score": 9.8,
                            "rationale": "Persona favors macro and valuation stories.",
                        }
                    ]
                )
            elif "ai infrastructure builder focused on model costs and chips" in lowered:
                content = json.dumps(
                    [
                        {
                            "index": 2,
                            "category": "AI & ML industry developments",
                            "score": 9.8,
                            "rationale": "Persona favors AI infrastructure and model-cost stories.",
                        }
                    ]
                )
            else:
                raise AssertionError("Persona text missing from ranking prompt.")
        else:
            if "macro investor focused on rates and valuations" in lowered:
                content = json.dumps(
                    {
                        "headline": "Rates reset changes software valuations",
                        "body": "\n".join(
                            [
                                "Key takeaways",
                                "- Rates reset changes software valuations in public markets.",
                                "- The repricing pressure is concentrated in growth names.",
                                "Why this matters to me",
                                "You care about rates and valuation resets. This directly affects your macro framing.",
                            ]
                        ),
                    }
                )
            elif "ai infrastructure builder focused on model costs and chips" in lowered:
                content = json.dumps(
                    {
                        "headline": "Open model pricing changed",
                        "body": "\n".join(
                            [
                                "Key takeaways",
                                "- Open model pricing changed and inference budgets moved again.",
                                "- The change alters platform-level deployment economics.",
                                "Why this matters to me",
                                "You care about model costs and chips. This directly affects infrastructure choices.",
                            ]
                        ),
                    }
                )
            else:
                raise AssertionError("Persona text missing from summary prompt.")

        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=usage,
        )


def build_persona_config(tmp_path, repo_root, persona_text: str):
    return write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "persona": {"text": persona_text},
            "email": {
                "digest_recipients": ["persona@example.com"],
                "digest_subject": "Persona Digest",
            },
            "additional_sources": {"enabled": True, "hours": 48},
            "limits": {
                "select_top_stories": 1,
                "final_top_stories": 1,
                "source_quotas": {"gmail": 0, "additional_source": 1},
            },
        },
    )


def seed_repository(config: dict):
    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")
    repository.upsert_article_snapshot(
        repository.upsert_story(
            {
                "source_type": "additional_source",
                "source_name": "Macro Wire",
                "subject": "[markets] Rates reset",
                "url": "https://example.com/markets/rates-reset",
                "anchor_text": "Rates reset changes software valuations",
                "context": "Macro context for valuations and rates.",
                "category": "Markets / stocks / macro / economy",
                "published_at": "2026-03-21T07:30:00+00:00",
                "summary": "Rates reset summary",
            },
            ingestion_run_id=ingestion_run_id,
        ),
        "Rates reset changes software valuations and reprices growth names.",
    )
    repository.upsert_article_snapshot(
        repository.upsert_story(
            {
                "source_type": "additional_source",
                "source_name": "AI Wire",
                "subject": "[ai] Open model pricing changed",
                "url": "https://example.com/ai/model-pricing",
                "anchor_text": "Open model pricing changed",
                "context": "AI pricing and chip context.",
                "category": "AI & ML industry developments",
                "published_at": "2026-03-21T06:00:00+00:00",
                "summary": "Pricing summary",
            },
            ingestion_run_id=ingestion_run_id,
        ),
        "Open model pricing changed and shifts inference budgets for builders.",
    )


def run_persona_delivery(main_module, config_path: str):
    main_module.CONFIG_PATH = config_path
    config = main_module.load_config()
    seed_repository(config)

    service = FakeGmailService(messages=[])
    sent_messages: list[dict] = []

    def fail_live_article_fetch(*args, **kwargs):
        raise AssertionError("Repository-backed persona test should not fetch articles live.")

    def fake_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        sent_messages.append(
            {
                "to": to_address,
                "subject": subject,
                "body": body,
                "html_body": html_body or "",
            }
        )

    main_module.fetch_article_text = fail_live_article_fetch
    main_module.send_email = fake_send_email
    main_module.run_job(config, service)
    return sent_messages[0]


def test_persona_changes_ranking_and_summary(monkeypatch, repo_root, tmp_path):
    main = importlib.import_module("main")
    monkeypatch.setattr(main, "OpenAI", PersonaAwareOpenAI)

    macro_config_path = build_persona_config(
        tmp_path / "macro",
        repo_root,
        "Macro investor focused on rates and valuations.",
    )
    ai_config_path = build_persona_config(
        tmp_path / "ai",
        repo_root,
        "AI infrastructure builder focused on model costs and chips.",
    )

    macro_payload = run_persona_delivery(main, str(macro_config_path))
    ai_payload = run_persona_delivery(main, str(ai_config_path))

    assert "Rates reset changes software valuations" in macro_payload["body"]
    assert "Open model pricing changed" not in macro_payload["body"]
    assert "You care about rates and valuation resets." in macro_payload["body"]

    assert "Open model pricing changed" in ai_payload["body"]
    assert "Rates reset changes software valuations" not in ai_payload["body"]
    assert "You care about model costs and chips." in ai_payload["body"]
