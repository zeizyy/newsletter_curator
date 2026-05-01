from __future__ import annotations

from .llm import generate_story_preference_memory_with_llm
from .observability import emit_event
from .repository import SQLiteRepository


def generate_subscriber_story_preference_memory(
    repository: SQLiteRepository,
    subscriber_id: int,
    *,
    model: str,
    click_limit: int = 50,
    client_factory=None,
) -> dict:
    subscriber = None
    with repository.connect() as connection:
        subscriber = connection.execute(
            """
            SELECT id, email_address
            FROM subscribers
            WHERE id = ?
            LIMIT 1
            """,
            (int(subscriber_id),),
        ).fetchone()
    if subscriber is None:
        return {"status": "missing_subscriber", "subscriber_id": int(subscriber_id)}

    profile = repository.get_subscriber_profile(int(subscriber_id))
    existing_memory = repository.get_subscriber_story_preference_memory(int(subscriber_id))
    since = str((existing_memory or {}).get("last_click_at") or "")
    new_clicks = repository.list_clicked_stories_for_subscriber(
        int(subscriber_id),
        since=since,
        limit=max(1, int(click_limit)),
    )
    if not new_clicks:
        emit_event(
            "story_preference_memory_skipped",
            subscriber_id=int(subscriber_id),
            reason="no_new_clicks",
        )
        return {
            "status": "skipped",
            "reason": "no_new_clicks",
            "subscriber_id": int(subscriber_id),
        }

    clicked_stories = repository.list_clicked_stories_for_subscriber(
        int(subscriber_id),
        limit=max(1, int(click_limit)),
    )
    usage_by_model: dict = {}
    kwargs = {}
    if client_factory is not None:
        kwargs["client_factory"] = client_factory
    memory_text = generate_story_preference_memory_with_llm(
        clicked_stories,
        usage_by_model,
        model,
        existing_memory=str((existing_memory or {}).get("memory_text") or ""),
        persona_text=str(profile.get("persona_text") or ""),
        **kwargs,
    )
    last_click_at = max(str(story.get("clicked_at") or "") for story in clicked_stories)
    memory = repository.upsert_subscriber_story_preference_memory(
        int(subscriber_id),
        memory_text=memory_text,
        last_click_at=last_click_at,
        clicked_story_count=len(clicked_stories),
        metadata={
            "model": model,
            "usage_by_model": usage_by_model,
            "new_click_count": len(new_clicks),
        },
    )
    emit_event(
        "story_preference_memory_generated",
        subscriber_id=int(subscriber_id),
        clicked_story_count=len(clicked_stories),
        new_click_count=len(new_clicks),
        model=model,
    )
    return {
        "status": "generated",
        "subscriber_id": int(subscriber_id),
        "email_address": str(subscriber["email_address"] or ""),
        "new_click_count": len(new_clicks),
        "clicked_story_count": len(clicked_stories),
        "memory": memory,
    }


def generate_story_preference_memories(
    repository: SQLiteRepository,
    *,
    model: str,
    subscriber_id: int | None = None,
    limit: int | None = None,
    click_limit: int = 50,
    client_factory=None,
) -> dict:
    if subscriber_id is not None:
        targets = [{"subscriber_id": int(subscriber_id)}]
    else:
        targets = repository.list_subscribers_with_new_clicks_for_memory(limit=limit)

    results = [
        generate_subscriber_story_preference_memory(
            repository,
            int(target["subscriber_id"]),
            model=model,
            click_limit=click_limit,
            client_factory=client_factory,
        )
        for target in targets
    ]
    return {
        "status": "completed",
        "target_count": len(targets),
        "generated_count": sum(1 for result in results if result.get("status") == "generated"),
        "skipped_count": sum(1 for result in results if result.get("status") == "skipped"),
        "results": results,
    }
