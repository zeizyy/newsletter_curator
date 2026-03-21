from __future__ import annotations

import json

from openai import OpenAI


def format_links_for_llm(items: list[dict]) -> str:
    lines = []
    for idx, item in enumerate(items, start=1):
        anchor_text = item.get("anchor_text", "")
        context = item.get("context", "")
        label = context or anchor_text
        lines.append(f"[{idx}] {label}".strip())
    return "\n\n".join(lines)


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
    client_factory=OpenAI,
) -> list[dict]:
    if not items:
        return []

    client = client_factory()
    system_prompt = (
        "You are a newsletter curator. Rank stories strictly by this priority order: "
        "Markets/stocks/macro/economy > Tech company news & strategy > AI & ML industry "
        "developments > Tech blogs > Interesting datapoints & anomalies. If two stories are "
        "from different tiers, always rank the higher-tier story above the lower-tier story, "
        "regardless of popularity. Within the same tier, score by relevance to these interests, "
        "timeliness, impact, and depth of insight. Penalize repetition, clickbait, or low-signal "
        "items. After scoring, enforce category diversity so the top selections include coverage "
        "across tech companies, AI/ML, macro/markets, deeper blogs/papers, and interesting "
        "datapoints. Exclude promos, subscriptions, and non-article links."
    )
    user_prompt = (
        "Here are extracted links with context. Select the top stories.\n"
        f"Return ONLY a JSON array of up to {top_stories} objects in ranked order.\n"
        "Score each story equally across timeliness, impact, and depth of insight; "
        "provide a final average score from 1-10.\n"
        "Each object must be: {\"index\": <int>, \"category\": <string>, "
        "\"score\": <number>, \"rationale\": <string>} "
        "where category is "
        "one of: Markets / stocks / macro / economy; Tech company news & strategy; "
        "AI & ML industry developments; Tech blogs; Interesting datapoints & anomalies.\n"
        "The \"index\" must refer to the numbered items in the input list below. Do NOT "
        "preserve input order; reorder by your ranking.\n"
        "No comments, no extra text, no trailing commas.\n\n"
        f"{format_links_for_llm(items)}"
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


def summarize_article_with_llm(
    article_text: str,
    usage_by_model: dict,
    lock,
    summary_model: str,
    *,
    client_factory=OpenAI,
) -> str:
    if not article_text:
        return "No article text available."

    client = client_factory()
    system_prompt = (
        "You are a concise financial/tech news analyst writing for a specific reader "
        "with priorities: Markets/stocks/macro/economy > Tech company news & strategy > "
        "AI & ML industry developments > Tech blogs > Interesting datapoints & anomalies."
    )
    user_prompt = (
        "Write a concise summary of the article below.\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\"headline\": <string>, \"body\": <string>}.\n"
        "The body should include:\n"
        "1) Key takeaways (3-5 bullets; be specific and informative).\n"
        "2) Why this matters to me (exactly 2 short sentences, max 45 words total).\n"
        "Keep the full body concise, but prioritize clarity in key takeaways.\n"
        "No extra text.\n\n"
        f"Article text:\n{article_text}"
    )
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


def extract_summary_json(summary: str) -> tuple[str, str]:
    try:
        data = json.loads(summary)
        if isinstance(data, dict):
            headline = data.get("headline", "").strip() or "Untitled"
            body = data.get("body", "").strip()
            return headline, body or summary
    except json.JSONDecodeError:
        pass
    return "Untitled", summary
