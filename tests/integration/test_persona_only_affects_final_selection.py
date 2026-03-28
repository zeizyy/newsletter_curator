from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from tests.fakes import FakeGmailService
from tests.helpers import write_temp_config


class PersonaBoundaryOpenAI:
    prompts: list[dict] = []

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    @classmethod
    def reset(cls) -> None:
        cls.prompts = []

    def create(self, *, model: str, messages: list[dict]):
        prompt_text = "\n".join(message["content"] for message in messages)
        lowered = prompt_text.lower()
        PersonaBoundaryOpenAI.prompts.append({"model": model, "prompt": prompt_text})

        if "deserve expensive summaries" in lowered:
            assert "macro investor focused on rates and valuations." not in lowered
            assert "ai infrastructure builder focused on model costs and chips." not in lowered
            content = json.dumps(
                [
                    {"index": 1, "score": 9.4, "rationale": "High-signal first candidate."},
                    {"index": 2, "score": 8.8, "rationale": "High-signal second candidate."},
                ]
            )
        elif "select the top stories" in lowered:
            if "macro investor focused on rates and valuations." in lowered:
                preferred_index = (
                    1
                    if "[1] rates reset changes software valuations" in lowered
                    or "[1] macro context for valuations and rates." in lowered
                    else 2
                )
                content = json.dumps(
                    [
                        {
                            "index": preferred_index,
                            "category": "Markets / stocks / macro / economy",
                            "score": 9.9,
                            "rationale": "Persona favors macro stories.",
                        }
                    ]
                )
            elif "ai infrastructure builder focused on model costs and chips." in lowered:
                preferred_index = (
                    1
                    if "[1] open model pricing changed" in lowered
                    or "[1] ai pricing and chip context." in lowered
                    else 2
                )
                content = json.dumps(
                    [
                        {
                            "index": preferred_index,
                            "category": "AI & ML industry developments",
                            "score": 9.9,
                            "rationale": "Persona favors AI infrastructure stories.",
                        }
                    ]
                )
            else:
                raise AssertionError("Persona text missing from final ranking prompt.")
        else:
            assert "macro investor focused on rates and valuations." not in lowered
            assert "ai infrastructure builder focused on model costs and chips." not in lowered
            if "rates reset changes software valuations" in lowered:
                content = json.dumps(
                    {
                        "headline": "Rates reset changes software valuations",
                        "body": "\n".join(
                            [
                                "Key takeaways",
                                "- Rates reset changes software valuations in public markets.",
                                "- The repricing pressure is concentrated in growth names.",
                                "Why this matters to me",
                                "This matters because repricing pressure can reset investor and operator expectations.",
                            ]
                        ),
                    }
                )
            elif "open model pricing changed" in lowered:
                content = json.dumps(
                    {
                        "headline": "Open model pricing changed",
                        "body": "\n".join(
                            [
                                "Key takeaways",
                                "- Open model pricing changed and inference budgets moved again.",
                                "- The change alters platform-level deployment economics.",
                                "Why this matters to me",
                                "This matters because pricing shifts can quickly reorder platform economics.",
                            ]
                        ),
                    }
                )
            else:
                raise AssertionError("Unexpected summary prompt.")

        usage = SimpleNamespace(prompt_tokens=12, completion_tokens=6, total_tokens=18)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=usage,
        )


def build_persona_config(tmp_path, persona_text: str):
    return write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "persona": {"text": persona_text},
            "email": {
                "digest_recipients": ["persona@example.com"],
                "digest_subject": "Persona Digest",
            },
            "additional_sources": {"enabled": True, "hours": 24},
            "limits": {
                "max_ingest_summaries": 2,
                "select_top_stories": 1,
                "final_top_stories": 1,
                "source_quotas": {"gmail": 0, "additional_source": 1},
            },
        },
    )


def fake_source_fetcher(_config: dict) -> list[dict]:
    now = datetime.now(UTC)
    return [
        {
            "source_type": "additional_source",
            "source_name": "Macro Wire",
            "subject": "[markets] Rates reset",
            "url": "https://example.com/markets/rates-reset",
            "anchor_text": "Rates reset changes software valuations",
            "context": "Macro context for valuations and rates.",
            "category": "Markets / stocks / macro / economy",
            "published_at": (now - timedelta(hours=2)).isoformat(),
        },
        {
            "source_type": "additional_source",
            "source_name": "AI Wire",
            "subject": "[ai] Open model pricing changed",
            "url": "https://example.com/ai/model-pricing",
            "anchor_text": "Open model pricing changed",
            "context": "AI pricing and chip context.",
            "category": "AI & ML industry developments",
            "published_at": (now - timedelta(hours=1)).isoformat(),
        },
    ]


def fake_article_fetcher(
    url: str,
    _max_chars: int,
    timeout: int = 15,
    retries: int = 2,
) -> dict:
    del timeout, retries
    if url.endswith("/rates-reset"):
        return {
            "article_text": "Rates reset changes software valuations and reprices growth names.",
            "document_title": "Rates reset changes software valuations",
            "document_excerpt": "Macro context for valuations and rates.",
        }
    if url.endswith("/model-pricing"):
        return {
            "article_text": "Open model pricing changed and shifts inference budgets for builders.",
            "document_title": "Open model pricing changed",
            "document_excerpt": "AI pricing and chip context.",
        }
    raise AssertionError(f"Unexpected URL {url}")


def run_persona_scenario(monkeypatch, tmp_path, persona_text: str):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")

    config_path = build_persona_config(tmp_path, persona_text)
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(main, "OpenAI", PersonaBoundaryOpenAI)
    monkeypatch.setattr(jobs, "OpenAI", PersonaBoundaryOpenAI)

    sent_messages: list[dict] = []

    def fake_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        sent_messages.append(
            {
                "to": to_address,
                "subject": subject,
                "body": body,
                "html_body": html_body or "",
            }
        )

    monkeypatch.setattr(main, "send_email", fake_send_email)

    PersonaBoundaryOpenAI.reset()
    config = main.load_config()
    repository = jobs.get_repository_from_config(config)
    fetch_result = jobs.run_fetch_sources_job(
        config,
        repository=repository,
        source_fetcher=fake_source_fetcher,
        article_fetcher=fake_article_fetcher,
    )
    stories = {
        story["url"]: story
        for story in repository.list_stories(source_type="additional_source")
    }
    delivery_result = main.run_job(config, FakeGmailService(messages=[]))
    return {
        "fetch_result": fetch_result,
        "delivery_result": delivery_result,
        "sent_message": sent_messages[0],
        "prompts": list(PersonaBoundaryOpenAI.prompts),
        "stories": stories,
    }


def test_persona_only_affects_final_selection(monkeypatch, tmp_path):
    macro = run_persona_scenario(
        monkeypatch,
        tmp_path / "macro",
        "Macro investor focused on rates and valuations.",
    )
    ai = run_persona_scenario(
        monkeypatch,
        tmp_path / "ai",
        "AI infrastructure builder focused on model costs and chips.",
    )

    assert macro["fetch_result"]["stories_persisted"] == 2
    assert ai["fetch_result"]["stories_persisted"] == 2
    assert (
        macro["stories"]["https://example.com/markets/rates-reset"]["summary_body"]
        == ai["stories"]["https://example.com/markets/rates-reset"]["summary_body"]
    )
    assert (
        macro["stories"]["https://example.com/ai/model-pricing"]["summary_body"]
        == ai["stories"]["https://example.com/ai/model-pricing"]["summary_body"]
    )

    for payload, persona_text in (
        (macro, "macro investor focused on rates and valuations."),
        (ai, "ai infrastructure builder focused on model costs and chips."),
    ):
        ranking_prompts = [
            prompt["prompt"].lower()
            for prompt in payload["prompts"]
            if "select the top stories" in prompt["prompt"].lower()
        ]
        scoring_prompts = [
            prompt["prompt"].lower()
            for prompt in payload["prompts"]
            if "deserve expensive summaries" in prompt["prompt"].lower()
        ]
        summary_prompts = [
            prompt["prompt"].lower()
            for prompt in payload["prompts"]
            if "write a concise summary of the article below." in prompt["prompt"].lower()
        ]

        assert ranking_prompts
        assert scoring_prompts
        assert summary_prompts
        assert any(persona_text in prompt for prompt in ranking_prompts)
        assert all(persona_text not in prompt for prompt in scoring_prompts)
        assert all(persona_text not in prompt for prompt in summary_prompts)

    assert "Rates reset changes software valuations" in macro["sent_message"]["body"]
    assert "Open model pricing changed" not in macro["sent_message"]["body"]
    assert "Open model pricing changed" in ai["sent_message"]["body"]
    assert "Rates reset changes software valuations" not in ai["sent_message"]["body"]
