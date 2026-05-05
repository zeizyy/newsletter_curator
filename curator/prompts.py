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


def preference_memory_clause(memory_text: str) -> str:
    cleaned = memory_text.strip()
    if not cleaned:
        return ""
    return f"\nLearned story preference memory from prior clicks:\n{cleaned}\n"


def ranking_system_guidance(persona_text: str, story_preference_memory: str) -> str:
    if persona_text.strip():
        memory_guidance = (
            " Use learned preference memory as supporting evidence for that persona."
            if story_preference_memory.strip()
            else ""
        )
        return (
            "Rank stories for the provided user persona. Score by fit to that reader lens, "
            f"timeliness, impact, and depth of insight.{memory_guidance}"
        )
    if story_preference_memory.strip():
        return (
            "Rank stories for the learned story preference memory. Score by fit to those "
            "observed preferences, timeliness, impact, and depth of insight."
        )
    return (
        "Rank stories by this category priority order: "
        f"{DEFAULT_PRIORITY_TEXT} "
        "Score by category priority, timeliness, impact, and depth of insight."
    )


def ranking_user_guidance(persona_text: str, story_preference_memory: str) -> str:
    if persona_text.strip():
        if story_preference_memory.strip():
            return (
                "Interpret relevance through the provided user persona. Use learned preference "
                "memory as additional evidence only when it fits that persona.\n"
            )
        return "Interpret relevance through the provided user persona.\n"
    if story_preference_memory.strip():
        return "Interpret relevance through the learned story preference memory.\n"
    return "Interpret relevance through the baseline category priority order.\n"


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
    story_preference_memory: str = "",
    preferred_sources: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, str]:
    system_prompt = (
        "You are a newsletter curator. "
        f"{ranking_system_guidance(persona_text, story_preference_memory)} "
        "Penalize repetition, clickbait, or low-signal items. After scoring, enforce category "
        "diversity where it does not displace clearly better reader-fit stories. Exclude "
        "promos, subscriptions, and non-article links."
        f"{persona_clause(persona_text)}"
        f"{preference_memory_clause(story_preference_memory)}"
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
        f"{ranking_user_guidance(persona_text, story_preference_memory)}"
        "No comments, no extra text, no trailing commas.\n\n"
        f"{format_links_for_llm(items)}"
    )
    return system_prompt, user_prompt


def format_clicked_stories_for_llm(clicked_stories: list[dict]) -> str:
    lines = []
    for idx, story in enumerate(clicked_stories, start=1):
        lines.append(
            "\n".join(
                [
                    f"[{idx}] {story.get('title', '')}".strip(),
                    f"Source: {story.get('source_name', '')}".strip(),
                    f"Category: {story.get('category', '')}".strip(),
                    f"Clicked at: {story.get('clicked_at', '')}".strip(),
                    f"Summary: {story.get('summary', '')}".strip(),
                    f"URL: {story.get('url', '')}".strip(),
                ]
            ).strip()
        )
    return "\n\n".join(lines)


def build_story_preference_memory_prompts(
    clicked_stories: list[dict],
    *,
    existing_memory: str = "",
    persona_text: str = "",
) -> tuple[str, str]:
    system_prompt = (
        "You maintain a compact read-only preference memory for a personalized newsletter. "
        "Infer stable story-selection preferences from clicked stories. Focus on durable topic, "
        "source, depth, business-model, market, technical, and novelty signals. Do not mention "
        "individual clicks unless they represent a reusable preference. Avoid sensitive personal "
        "attributes and do not invent facts."
        f"{persona_clause(persona_text)}"
    )
    previous = existing_memory.strip() or "No previous memory."
    user_prompt = (
        "Update the user's story preference memory using the clicked stories below.\n"
        "Return only concise plain text, 3-7 bullets. Each bullet should be actionable for "
        "future story ranking.\n\n"
        f"Previous memory:\n{previous}\n\n"
        f"Clicked stories:\n{format_clicked_stories_for_llm(clicked_stories)}"
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
