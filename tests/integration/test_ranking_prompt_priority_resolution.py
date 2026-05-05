from __future__ import annotations

from curator.prompts import DEFAULT_PRIORITY_TEXT, build_ranking_prompts


def test_ranking_prompt_uses_persona_without_default_priority_fallback_logic():
    system_prompt, user_prompt = build_ranking_prompts(
        [
            {
                "anchor_text": "Open model pricing changed",
                "context": "AI pricing and chip context.",
            },
            {
                "anchor_text": "Rates reset changes software valuations",
                "context": "Macro context for valuations and rates.",
            },
        ],
        2,
        persona_text="AI infrastructure builder focused on model costs and chips.",
        story_preference_memory="- Prefer measurable inference cost and adoption signals.",
        preferred_sources=["AI Wire"],
    )

    combined_prompt = f"{system_prompt}\n{user_prompt}"

    assert DEFAULT_PRIORITY_TEXT not in combined_prompt
    assert "strictly by this priority order" not in combined_prompt
    assert "always rank the higher-tier story" not in combined_prompt
    assert "fallback" not in combined_prompt
    assert "AI infrastructure builder focused on model costs and chips." in system_prompt
    assert "Rank stories for the provided user persona." in system_prompt
    assert "Use learned preference memory as supporting evidence for that persona." in system_prompt
    assert "Interpret relevance through the provided user persona." in user_prompt
    assert "hard allowlist" not in combined_prompt
    assert "hard filter" not in combined_prompt
    assert "AI Wire" not in combined_prompt


def test_ranking_prompt_uses_default_priority_when_persona_and_memory_are_empty():
    system_prompt, user_prompt = build_ranking_prompts(
        [{"anchor_text": "Rates reset", "context": "Macro context."}],
        1,
        persona_text="",
        story_preference_memory="",
    )

    combined_prompt = f"{system_prompt}\n{user_prompt}"

    assert DEFAULT_PRIORITY_TEXT in system_prompt
    assert "Rank stories by this category priority order:" in system_prompt
    assert "Interpret relevance through the baseline category priority order." in user_prompt
    assert "User persona:" not in combined_prompt
    assert "Learned story preference memory" not in combined_prompt
