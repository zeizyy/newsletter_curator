from __future__ import annotations

import json

from openai import OpenAI

from .prompts import (
    build_story_preference_memory_prompts,
    build_ingest_scoring_prompts,
    build_ranking_prompts,
    build_summary_prompts,
    format_links_for_llm,
)
from .summary_format import extract_structured_summary


def parse_index_list(text: str) -> list[int]:
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [int(x) for x in data if isinstance(x, (int, float, str)) and str(x).isdigit()]
    except json.JSONDecodeError:
        pass

    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, list):
                return [int(x) for x in data if isinstance(x, (int, float, str)) and str(x).isdigit()]
        except json.JSONDecodeError:
            return []
    return []


def parse_selection_items(text: str) -> list[dict]:
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


def select_top_stories(
    items: list[dict],
    usage_by_model: dict,
    top_stories: int,
    reasoning_model: str,
    *,
    persona_text: str = "",
    story_preference_memory: str = "",
    preferred_sources: list[str] | tuple[str, ...] | None = None,
    client_factory=OpenAI,
) -> list[dict]:
    if not items:
        return []

    client = client_factory()
    system_prompt, user_prompt = build_ranking_prompts(
        items,
        top_stories,
        persona_text,
        story_preference_memory,
        preferred_sources,
    )
    response = client.chat.completions.create(
        model=reasoning_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    usage = response.usage
    if usage:
        stats = usage_by_model.setdefault(
            reasoning_model, {"input": 0, "output": 0, "total": 0}
        )
        stats["input"] += usage.prompt_tokens or 0
        stats["output"] += usage.completion_tokens or 0
        stats["total"] += usage.total_tokens or 0
    content = response.choices[0].message.content.strip()
    selections = parse_selection_items(content)
    if not selections:
        return []

    max_index = len(items)
    deduped = []
    seen = set()
    for selection in selections:
        idx = selection.get("index")
        if isinstance(idx, (int, float)) and int(idx) == idx:
            idx = int(idx)
        if isinstance(idx, int) and 1 <= idx <= max_index and idx not in seen:
            item = dict(items[idx - 1])
            item["category"] = selection.get("category", "")
            item["score"] = selection.get("score", "")
            item["rationale"] = selection.get("rationale", "")
            deduped.append(item)
            seen.add(idx)
        if len(deduped) >= top_stories:
            break
    return deduped


def generate_story_preference_memory_with_llm(
    clicked_stories: list[dict],
    usage_by_model: dict,
    model: str,
    *,
    existing_memory: str = "",
    persona_text: str = "",
    client_factory=OpenAI,
) -> str:
    if not clicked_stories:
        return ""

    client = client_factory()
    system_prompt, user_prompt = build_story_preference_memory_prompts(
        clicked_stories,
        existing_memory=existing_memory,
        persona_text=persona_text,
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    usage = response.usage
    if usage:
        stats = usage_by_model.setdefault(model, {"input": 0, "output": 0, "total": 0})
        stats["input"] += usage.prompt_tokens or 0
        stats["output"] += usage.completion_tokens or 0
        stats["total"] += usage.total_tokens or 0
    return response.choices[0].message.content.strip()


def summarize_article_with_llm(
    article_text: str,
    usage_by_model: dict,
    lock,
    summary_model: str,
    *,
    persona_text: str = "",
    client_factory=OpenAI,
) -> str:
    if not article_text:
        return "No article text available."

    client = client_factory()
    system_prompt, user_prompt = build_summary_prompts(article_text, persona_text)
    response = client.chat.completions.create(
        model=summary_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    usage = response.usage
    if usage:
        with lock:
            stats = usage_by_model.setdefault(
                summary_model, {"input": 0, "output": 0, "total": 0}
            )
            stats["input"] += usage.prompt_tokens or 0
            stats["output"] += usage.completion_tokens or 0
            stats["total"] += usage.total_tokens or 0
    return response.choices[0].message.content.strip()


def score_story_candidates(
    items: list[dict],
    usage_by_model: dict,
    top_stories: int,
    reasoning_model: str,
    *,
    persona_text: str = "",
    client_factory=OpenAI,
) -> list[dict]:
    if not items:
        return []

    client = client_factory()
    system_prompt, user_prompt = build_ingest_scoring_prompts(items, top_stories, persona_text)
    response = client.chat.completions.create(
        model=reasoning_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    usage = response.usage
    if usage:
        stats = usage_by_model.setdefault(
            reasoning_model, {"input": 0, "output": 0, "total": 0}
        )
        stats["input"] += usage.prompt_tokens or 0
        stats["output"] += usage.completion_tokens or 0
        stats["total"] += usage.total_tokens or 0

    selections = parse_selection_items(response.choices[0].message.content.strip())
    if not selections:
        return []

    ranked: list[dict] = []
    seen = set()
    max_index = len(items)
    for selection in selections:
        idx = selection.get("index")
        if isinstance(idx, (int, float)) and int(idx) == idx:
            idx = int(idx)
        if not isinstance(idx, int) or not (1 <= idx <= max_index) or idx in seen:
            continue
        item = dict(items[idx - 1])
        item["score"] = selection.get("score", "")
        item["rationale"] = selection.get("rationale", "")
        ranked.append(item)
        seen.add(idx)
        if len(ranked) >= top_stories:
            break
    return ranked


def extract_summary_json(summary: str) -> tuple[str, str]:
    normalized = extract_structured_summary(summary, fallback_body=summary)
    headline = str(normalized.get("headline", "") or "").strip() or "Untitled"
    body = str(normalized.get("body", "") or "").strip()
    return headline, body or str(summary or "")
