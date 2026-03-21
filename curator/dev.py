from __future__ import annotations

import json


def fake_select_top_stories(
    items: list[dict],
    usage_by_model: dict,
    top_stories: int,
    reasoning_model: str,
) -> list[dict]:
    if not items:
        return []

    stats = usage_by_model.setdefault(reasoning_model, {"input": 0, "output": 0, "total": 0})
    stats["input"] += len(items)
    stats["output"] += min(len(items), top_stories)
    stats["total"] += stats["input"] + stats["output"]

    ranked = []
    for index, item in enumerate(items[:top_stories], start=1):
        ranked_item = dict(item)
        ranked_item["category"] = item.get("category") or "Interesting datapoints & anomalies"
        ranked_item["score"] = 10 - index
        ranked_item["rationale"] = "Deterministic development ranking."
        ranked.append(ranked_item)
    return ranked


def fake_summarize_article(
    article_text: str,
    usage_by_model: dict,
    lock,
    summary_model: str,
) -> str:
    headline = " ".join(article_text.split()[:6]) or "Untitled"
    body = "\n".join(
        [
            "Key takeaways",
            f"- {headline} is available from the canned repository.",
            "- Development mode uses deterministic local summaries.",
            "Why this matters to me",
            "This matters because development can run fully offline.",
        ]
    )
    with lock:
        stats = usage_by_model.setdefault(summary_model, {"input": 0, "output": 0, "total": 0})
        stats["input"] += 1
        stats["output"] += 1
        stats["total"] += 2
    return json.dumps({"headline": headline, "body": body})
