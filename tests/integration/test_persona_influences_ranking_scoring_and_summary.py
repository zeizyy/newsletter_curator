from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from tests.fakes import FakeGmailService
from tests.helpers import write_temp_config


class PersonaTracingOpenAI:
    prompts: list[dict] = []

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    @classmethod
    def reset(cls) -> None:
        cls.prompts = []

    def create(self, *, model: str, messages: list[dict]):
        prompt_text = "\n".join(message["content"] for message in messages)
        lowered = prompt_text.lower()
        PersonaTracingOpenAI.prompts.append({"model": model, "prompt": prompt_text})

        if "deserve expensive summaries" in lowered:
            content = json.dumps(self._selection_for_persona(lowered))
        elif "select the top stories" in lowered:
            content = json.dumps(self._selection_for_persona(lowered, include_category=True))
        else:
            content = json.dumps(self._summary_for_persona(lowered))

        usage = SimpleNamespace(prompt_tokens=12, completion_tokens=6, total_tokens=18)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=usage,
        )

    def _selection_for_persona(self, lowered: str, *, include_category: bool = False) -> list[dict]:
        if "macro investor focused on rates and valuations." in lowered:
            preferred_index = (
                1
                if "[1] rates reset changes software valuations" in lowered
                or "[1] macro context for valuations and rates." in lowered
                else 2
            )
            payload = [
                {
                    "index": preferred_index,
                    "score": 9.9,
                    "rationale": "Persona favors macro and valuation resets.",
                },
                {
                    "index": 1 if preferred_index == 2 else 2,
                    "score": 7.1,
                    "rationale": "Still relevant, but less aligned to the macro persona.",
                },
            ]
            category = "Markets / stocks / macro / economy"
        elif "ai infrastructure builder focused on model costs and chips." in lowered:
            preferred_index = (
                1
                if "[1] open model pricing changed" in lowered
                or "[1] ai pricing and chip context." in lowered
                else 2
            )
            payload = [
                {
                    "index": preferred_index,
                    "score": 9.9,
                    "rationale": "Persona favors model-cost and chip stories.",
                },
                {
                    "index": 1 if preferred_index == 2 else 2,
                    "score": 7.1,
                    "rationale": "Still relevant, but less aligned to the AI infra persona.",
                },
            ]
            category = "AI & ML industry developments"
        else:
            raise AssertionError("Persona text missing from prompt.")

        if include_category:
            for item in payload:
                item["category"] = category
        return payload

    def _summary_for_persona(self, lowered: str) -> dict:
        if "rates reset changes software valuations" in lowered:
            headline = "Rates reset changes software valuations"
            body = [
                "Key takeaways",
                "- Rates reset changes software valuations in public markets.",
                "- The repricing pressure is concentrated in growth names.",
            ]
        elif "open model pricing changed" in lowered:
            headline = "Open model pricing changed"
            body = [
                "Key takeaways",
                "- Open model pricing changed and inference budgets moved again.",
                "- The change alters platform-level deployment economics.",
            ]
        else:
            raise AssertionError("Unexpected article text in summary prompt.")

        if "macro investor focused on rates and valuations." in lowered:
            body.extend(
                [
                    "Why this matters to me",
                    "You care about rates and valuation resets. This directly affects your macro framing.",
                ]
            )
        elif "ai infrastructure builder focused on model costs and chips." in lowered:
            body.extend(
                [
                    "Why this matters to me",
                    "You care about model costs and chips. This directly affects infrastructure choices.",
                ]
            )
        else:
            raise AssertionError("Persona text missing from summary prompt.")

        return {"headline": headline, "body": "\n".join(body)}


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


def fake_article_fetcher(url: str, _max_chars: int) -> dict:
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
    monkeypatch.setattr(main, "OpenAI", PersonaTracingOpenAI)
    monkeypatch.setattr(jobs, "OpenAI", PersonaTracingOpenAI)

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

    PersonaTracingOpenAI.reset()
    config = main.load_config()
    repository = jobs.get_repository_from_config(config)
    fetch_result = jobs.run_fetch_sources_job(
        config,
        repository=repository,
        source_fetcher=fake_source_fetcher,
        article_fetcher=fake_article_fetcher,
    )
    delivery_result = main.run_job(config, FakeGmailService(messages=[]))
    return {
        "fetch_result": fetch_result,
        "delivery_result": delivery_result,
        "sent_message": sent_messages[0],
        "prompts": list(PersonaTracingOpenAI.prompts),
    }


def test_persona_influences_ranking_scoring_and_summary(monkeypatch, tmp_path):
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

    macro_prompts = "\n".join(prompt["prompt"] for prompt in macro["prompts"]).lower()
    ai_prompts = "\n".join(prompt["prompt"] for prompt in ai["prompts"]).lower()

    assert "macro investor focused on rates and valuations." in macro_prompts
    assert "deserve expensive summaries" in macro_prompts
    assert "select the top stories" in macro_prompts
    assert "why this matters to me" in macro_prompts

    assert "ai infrastructure builder focused on model costs and chips." in ai_prompts
    assert "deserve expensive summaries" in ai_prompts
    assert "select the top stories" in ai_prompts
    assert "why this matters to me" in ai_prompts

    assert "Rates reset changes software valuations" in macro["sent_message"]["body"]
    assert "Open model pricing changed" not in macro["sent_message"]["body"]
    assert "You care about rates and valuation resets." in macro["sent_message"]["body"]

    assert "Open model pricing changed" in ai["sent_message"]["body"]
    assert "Rates reset changes software valuations" not in ai["sent_message"]["body"]
    assert "You care about model costs and chips." in ai["sent_message"]["body"]
