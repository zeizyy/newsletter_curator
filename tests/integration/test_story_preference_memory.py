from __future__ import annotations

from curator.preference_memory import generate_story_preference_memories
from curator.repository import SQLiteRepository
from tests.fakes import FakeOpenAI


def test_story_preference_memory_generates_only_after_new_clicks(tmp_path):
    repository = SQLiteRepository(tmp_path / "curator.sqlite3")
    repository.initialize()
    subscriber = repository.upsert_subscriber("reader@example.com")
    repository.upsert_subscriber_profile(
        int(subscriber["id"]),
        persona_text="AI infrastructure investor.",
    )
    newsletter_id = repository.upsert_daily_newsletter(
        newsletter_date="2026-04-30",
        audience_key="audience",
        issue_type="daily",
        subject="AI Signal",
        body="Body",
        html_body="<a data-curator-track-link=\"1\" href=\"https://example.com/ai/chips\">Chips</a>",
        content={},
        selected_items=[
            {
                "title": "GPU supply reset",
                "url": "https://example.com/ai/chips",
                "source_name": "AI Wire",
                "source_type": "additional_source",
                "category": "AI & ML industry developments",
                "summary_body": "GPU supply changed inference economics.",
            }
        ],
        metadata={},
    )
    tracked_links = repository.ensure_tracked_links(
        int(newsletter_id),
        [
            {
                "title": "GPU supply reset",
                "url": "https://example.com/ai/chips",
            }
        ],
        subscriber_id=int(subscriber["id"]),
    )
    second_subscriber = repository.upsert_subscriber("other@example.com")
    second_tracked_links = repository.ensure_tracked_links(
        int(newsletter_id),
        [
            {
                "title": "GPU supply reset",
                "url": "https://example.com/ai/chips",
            }
        ],
        subscriber_id=int(second_subscriber["id"]),
    )

    assert tracked_links[0]["click_token"] != second_tracked_links[0]["click_token"]
    click = repository.record_newsletter_click(str(tracked_links[0]["click_token"]))
    assert click is not None
    assert click["subscriber_id"] == int(subscriber["id"])

    fake_openai = FakeOpenAI()
    result = generate_story_preference_memories(
        repository,
        model="gpt-5-mini",
        client_factory=lambda: fake_openai,
    )

    assert result["generated_count"] == 1
    memory = repository.get_subscriber_story_preference_memory(int(subscriber["id"]))
    assert memory is not None
    assert "AI infrastructure" in memory["memory_text"]
    assert memory["clicked_story_count"] == 1

    second_result = generate_story_preference_memories(
        repository,
        model="gpt-5-mini",
        client_factory=lambda: fake_openai,
    )

    assert second_result["target_count"] == 0
    assert len(fake_openai.calls) == 1
