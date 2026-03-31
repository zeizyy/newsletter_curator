from __future__ import annotations

DEFAULT_PRIORITY_TEXT = (
    "Markets/stocks/macro/economy > Tech company news & strategy > "
    "AI & ML industry developments > Tech blogs > Interesting datapoints & anomalies."
)


def persona_clause(persona_text: str) -> str:
    cleaned = persona_text.strip()
    if not cleaned:
        return ""
    return f"\nUser persona:\n{cleaned}\n"


def preferred_sources_clause(preferred_sources: list[str] | tuple[str, ...] | None) -> str:
    normalized = [str(source).strip() for source in preferred_sources or [] if str(source).strip()]
    if not normalized:
        return ""
    listed_sources = ", ".join(normalized)
    return (
        "\nPreferred sources to softly uprank when quality is otherwise comparable:\n"
        f"{listed_sources}\n"
        "Treat this as an uprank signal, not a hard filter. Do not exclude stronger stories solely "
        "because they come from other sources.\n"
    )


def format_links_for_llm(items: list[dict]) -> str:
    lines = []
    for idx, item in enumerate(items, start=1):
        anchor_text = item.get("anchor_text", "")
        context = item.get("context", "")
        label = context or anchor_text
        lines.append(f"[{idx}] {label}".strip())
    return "\n\n".join(lines)


def format_ingest_candidates_for_llm(items: list[dict]) -> str:
    lines = []
    for idx, item in enumerate(items, start=1):
        headline = item.get("anchor_text", "") or item.get("subject", "") or item.get("url", "")
        source_name = item.get("source_name", "")
        category = item.get("category", "")
        context = item.get("context", "")
        excerpt = item.get("article_excerpt", "")
        lines.append(
            "\n".join(
                [
                    f"[{idx}] {headline}".strip(),
                    f"Source: {source_name}".strip(),
                    f"Category: {category}".strip(),
                    f"Context: {context}".strip(),
                    f"Excerpt: {excerpt}".strip(),
                ]
            ).strip()
        )
    return "\n\n".join(lines)


def build_ranking_prompts(
    items: list[dict],
    top_stories: int,
    persona_text: str = "",
    preferred_sources: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, str]:
    system_prompt = (
        "You are a newsletter curator. Rank stories strictly by this priority order: "
        f"{DEFAULT_PRIORITY_TEXT} "
        "If two stories are from different tiers, always rank the higher-tier story above the "
        "lower-tier story, regardless of popularity. Within the same tier, score by relevance "
        "to these interests, timeliness, impact, and depth of insight. Penalize repetition, "
        "clickbait, or low-signal items. After scoring, enforce category diversity so the top "
        "selections include coverage across tech companies, AI/ML, macro/markets, deeper "
        "blogs/papers, and interesting datapoints. Exclude promos, subscriptions, and "
        "non-article links."
        f"{persona_clause(persona_text)}"
        f"{preferred_sources_clause(preferred_sources)}"
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
        "If a persona is provided, interpret relevance through that reader's priorities while "
        "still respecting the global tier ordering.\n"
        "If preferred sources are provided, use them only as a soft uprank signal when story "
        "quality is otherwise close.\n"
        "No comments, no extra text, no trailing commas.\n\n"
        f"{format_links_for_llm(items)}"
    )
    return system_prompt, user_prompt


def build_summary_prompts(article_text: str, persona_text: str = "") -> tuple[str, str]:
    system_prompt = (
        "You are a concise financial/tech news analyst writing for a broad financial and "
        f"technology readership with priorities: {DEFAULT_PRIORITY_TEXT}"
    )
    user_prompt = (
        "Write a concise summary of the article below.\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\"headline\": <string>, \"key_takeaways\": <array of strings>, "
        "\"why_this_matters\": <string>}.\n"
        "\"key_takeaways\" must contain 3-5 bullets and each bullet must be specific and informative.\n"
        "\"why_this_matters\" must be exactly 2 short sentences with a 45 word maximum.\n"
        "Do not include markdown headings or labels inside the values.\n"
        "No extra text.\n\n"
        f"Article text:\n{article_text}"
    )
    return system_prompt, user_prompt


def build_ingest_scoring_prompts(
    items: list[dict],
    top_stories: int,
    persona_text: str = "",
) -> tuple[str, str]:
    system_prompt = (
        "You are triaging fetched article candidates before expensive summarization. "
        "Pick the highest-value stories using only the provided title, source, context, "
        "category, and short article excerpt. Prefer concrete, strategic, technically meaningful, "
        "or economically revealing stories. Penalize repetition, fluff, low-signal roundups, "
        "and generic promo-style items."
    )
    user_prompt = (
        "Here are fetched article candidates. Select which ones deserve expensive summaries.\n"
        f"Return ONLY a JSON array of up to {top_stories} objects in ranked order.\n"
        "Each object must be: {\"index\": <int>, \"score\": <number>, \"rationale\": <string>}.\n"
        "Score on a 1-10 scale based on likely value to the reader.\n"
        "The \"index\" must refer to the numbered items below. No extra text.\n\n"
        f"{format_ingest_candidates_for_llm(items)}"
    )
    return system_prompt, user_prompt
