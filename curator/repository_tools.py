from __future__ import annotations

from .repository import SQLiteRepository
from .story_feed import RECENT_STORY_WINDOW_HOURS, list_recent_story_feed, resolve_database_path

RECENT_STORIES_TOOL = "list_recent_stories"
SEARCH_RECENT_STORIES_TOOL = "search_recent_stories"
GET_STORY_DETAILS_TOOL = "get_story_details"
MIN_WINDOW_HOURS = 1
MAX_WINDOW_HOURS = 168
MAX_SEARCH_LIMIT = 12
DEFAULT_SEARCH_LIMIT = 8
DEFAULT_DETAIL_CHAR_LIMIT = 3500
MAX_DETAIL_CHAR_LIMIT = 12000
DEFAULT_TOOL_RESULT_CHAR_LIMIT = 7000
MIN_TOOL_RESULT_CHAR_LIMIT = 1000


def _story_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "story_key",
            "source_type",
            "source_name",
            "subject",
            "url",
            "canonical_url",
            "anchor_text",
            "context",
            "category",
            "published_at",
            "first_seen_at",
            "last_seen_at",
            "effective_timestamp",
            "summary",
            "summary_headline",
            "summary_body",
            "article_fetched_at",
            "paywall_detected",
            "paywall_reason",
            "summarized_at",
        ],
        "properties": {
            "id": {"type": "integer"},
            "story_key": {"type": "string"},
            "source_type": {"type": "string"},
            "source_name": {"type": "string"},
            "subject": {"type": "string"},
            "url": {"type": "string"},
            "canonical_url": {"type": "string"},
            "anchor_text": {"type": "string"},
            "context": {"type": "string"},
            "category": {"type": "string"},
            "published_at": {"type": ["string", "null"]},
            "first_seen_at": {"type": "string"},
            "last_seen_at": {"type": "string"},
            "effective_timestamp": {"type": "string"},
            "summary": {"type": "string"},
            "summary_headline": {"type": "string"},
            "summary_body": {"type": "string"},
            "article_fetched_at": {"type": ["string", "null"]},
            "paywall_detected": {"type": "boolean"},
            "paywall_reason": {"type": ["string", "null"]},
            "summarized_at": {"type": ["string", "null"]},
        },
    }


def build_recent_stories_tool() -> dict:
    title_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "title"],
        "properties": {
            "id": {"type": "integer"},
            "title": {"type": "string"},
        },
    }
    return {
        "name": RECENT_STORIES_TOOL,
        "title": "List Recent Story Headlines",
        "description": "Lists stored story headlines from a recent window. Use for repository headline or roundup requests: recent stories, top news, date ranges, today, or yesterday. Not for definitions, background, implications, or general synthesis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "minimum": MIN_WINDOW_HOURS, "maximum": MAX_WINDOW_HOURS},
                "source_type": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_LIMIT},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["window_hours", "story_count", "stories"],
            "properties": {
                "window_hours": {"type": "integer"},
                "story_count": {"type": "integer"},
                "stories": {"type": "array", "items": title_schema},
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }


def build_search_recent_stories_tool() -> dict:
    snippet_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "title",
            "url",
            "source_name",
            "source_type",
            "published_at",
            "effective_timestamp",
            "category",
            "paywall_detected",
            "paywall_reason",
            "summary_headline",
            "summary_body",
            "context",
        ],
        "properties": {
            "id": {"type": "integer"},
            "title": {"type": "string"},
            "url": {"type": "string"},
            "source_name": {"type": "string"},
            "source_type": {"type": "string"},
            "published_at": {"type": ["string", "null"]},
            "effective_timestamp": {"type": "string"},
            "category": {"type": "string"},
            "paywall_detected": {"type": "boolean"},
            "paywall_reason": {"type": ["string", "null"]},
            "summary_headline": {"type": "string"},
            "summary_body": {"type": "string"},
            "context": {"type": "string"},
        },
    }
    return {
        "name": SEARCH_RECENT_STORIES_TOOL,
        "title": "Search Recent Story Snippets",
        "description": "Searches stored story snippets by topic, entity, company, person, product, or event. Use when the user explicitly asks whether the stored corpus contains a topic or asks for repository-backed stories about it. Not for definitions, background, implications, or general synthesis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "hours": {"type": "integer", "minimum": MIN_WINDOW_HOURS, "maximum": MAX_WINDOW_HOURS},
                "source_type": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_LIMIT},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["generated_at", "query", "window_hours", "story_count", "stories"],
            "properties": {
                "generated_at": {"type": "string"},
                "query": {"type": "string"},
                "window_hours": {"type": "integer"},
                "story_count": {"type": "integer"},
                "stories": {"type": "array", "items": snippet_schema},
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }


def build_story_details_tool() -> dict:
    return {
        "name": GET_STORY_DETAILS_TOOL,
        "title": "Get Story Details",
        "description": "Returns one stored story with its summary and source metadata. Use only when a specific repository story is identified and the user asks what the stored story/source/article says, requests citation/source details, or asks to verify a claim against that story. Not for definitions, background, implications, or general synthesis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "story_id": {"type": "integer"},
                "max_article_chars": {
                    "type": "integer",
                    "minimum": 200,
                    "maximum": MAX_DETAIL_CHAR_LIMIT,
                    "description": "Deprecated compatibility field; story detail responses return summaries only.",
                },
            },
            "required": ["story_id"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "id",
                "title",
                "url",
                "source_name",
                "source_type",
                "published_at",
                "category",
                "summary_headline",
                "summary_body",
            ],
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "url": {"type": "string"},
                "source_name": {"type": "string"},
                "source_type": {"type": "string"},
                "published_at": {"type": ["string", "null"]},
                "category": {"type": "string"},
                "summary_headline": {"type": "string"},
                "summary_body": {"type": "string"},
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }


def parse_list_recent_stories_arguments(arguments: object) -> tuple[int, str | None, int]:
    if arguments in (None, {}):
        return RECENT_STORY_WINDOW_HOURS, None, DEFAULT_SEARCH_LIMIT
    if not isinstance(arguments, dict):
        raise ValueError("list_recent_stories arguments must be an object.")
    unexpected = sorted(set(arguments) - {"hours", "source_type", "limit"})
    if unexpected:
        raise ValueError(f"Unsupported list_recent_stories arguments: {', '.join(unexpected)}")
    limit = arguments.get("limit", DEFAULT_SEARCH_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer.")
    if limit < 1 or limit > MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}.")
    return (
        _parse_hours(arguments.get("hours"), default=RECENT_STORY_WINDOW_HOURS),
        _parse_optional_string(arguments.get("source_type"), field_name="source_type"),
        limit,
    )


def parse_search_recent_stories_arguments(arguments: object) -> tuple[str, int, str | None, int]:
    if not isinstance(arguments, dict):
        raise ValueError("search_recent_stories arguments must be an object.")
    unexpected = sorted(set(arguments) - {"query", "hours", "source_type", "limit"})
    if unexpected:
        raise ValueError(f"Unsupported search_recent_stories arguments: {', '.join(unexpected)}")
    query = _parse_optional_string(arguments.get("query"), field_name="query")
    if not query:
        raise ValueError("query is required.")
    limit = arguments.get("limit", DEFAULT_SEARCH_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer.")
    if limit < 1 or limit > MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}.")
    return (
        query,
        _parse_hours(arguments.get("hours"), default=RECENT_STORY_WINDOW_HOURS),
        _parse_optional_string(arguments.get("source_type"), field_name="source_type"),
        limit,
    )


def parse_story_details_arguments(arguments: object) -> tuple[int, int]:
    if not isinstance(arguments, dict):
        raise ValueError("get_story_details arguments must be an object.")
    unexpected = sorted(set(arguments) - {"story_id", "max_article_chars"})
    if unexpected:
        raise ValueError(f"Unsupported get_story_details arguments: {', '.join(unexpected)}")
    story_id = arguments.get("story_id")
    if isinstance(story_id, bool) or not isinstance(story_id, int):
        raise ValueError("story_id must be an integer.")
    max_article_chars = arguments.get("max_article_chars", DEFAULT_DETAIL_CHAR_LIMIT)
    if isinstance(max_article_chars, bool) or not isinstance(max_article_chars, int):
        raise ValueError("max_article_chars must be an integer.")
    if max_article_chars < 200 or max_article_chars > MAX_DETAIL_CHAR_LIMIT:
        raise ValueError(f"max_article_chars must be between 200 and {MAX_DETAIL_CHAR_LIMIT}.")
    return story_id, max_article_chars


def list_recent_stories(
    config: dict,
    *,
    window_hours: int,
    source_type: str | None,
    limit: int,
) -> dict:
    payload = list_recent_story_feed(config, window_hours=window_hours, source_type=source_type)
    stories = [_normalize_story_headline(story) for story in payload["stories"][:limit]]
    return {
        "window_hours": window_hours,
        "story_count": len(stories),
        "stories": stories,
    }


def search_recent_stories(
    config: dict,
    *,
    query: str,
    window_hours: int,
    source_type: str | None,
    limit: int,
) -> dict:
    payload = list_recent_story_feed(config, window_hours=window_hours, source_type=source_type)
    matching = [_normalize_story_snippet(story) for story in payload["stories"] if _search_story_match(story, query)]
    return {
        "generated_at": payload["generated_at"],
        "query": query,
        "window_hours": window_hours,
        "story_count": len(matching[:limit]),
        "stories": matching[:limit],
    }


def get_story_details(config: dict, *, story_id: int, max_article_chars: int) -> dict:
    del max_article_chars
    repository = SQLiteRepository(resolve_database_path(config))
    repository.initialize()
    story = next((item for item in repository.list_stories() if int(item.get("id", 0) or 0) == story_id), None)
    if story is None:
        raise ValueError(f"Story {story_id} was not found.")
    return {
        "id": int(story["id"]),
        "title": _story_title(story),
        "url": str(story.get("url", "") or ""),
        "source_name": str(story.get("source_name", "") or ""),
        "source_type": str(story.get("source_type", "") or ""),
        "published_at": story.get("published_at"),
        "effective_timestamp": str(story.get("effective_timestamp", "") or ""),
        "category": str(story.get("category", "") or ""),
        "paywall_detected": bool(story.get("paywall_detected", False)),
        "paywall_reason": story.get("paywall_reason"),
        "summary_headline": str(story.get("summary_headline", "") or ""),
        "summary_body": str(story.get("summary_body", "") or str(story.get("summary", "") or "")),
    }


def _parse_hours(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("hours must be an integer.")
    if value < MIN_WINDOW_HOURS or value > MAX_WINDOW_HOURS:
        raise ValueError(f"hours must be between {MIN_WINDOW_HOURS} and {MAX_WINDOW_HOURS}.")
    return value


def _parse_optional_string(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    normalized = value.strip()
    return normalized or None


def _search_story_match(story: dict, query: str) -> bool:
    haystack = " ".join(
        [
            str(story.get("subject", "")),
            str(story.get("anchor_text", "")),
            str(story.get("context", "")),
            str(story.get("category", "")),
            str(story.get("summary", "")),
            str(story.get("summary_headline", "")),
            str(story.get("summary_body", "")),
            str(story.get("source_name", "")),
        ]
    ).lower()
    terms = [term for term in query.lower().split() if term]
    return bool(terms) and all(term in haystack for term in terms)


def _story_title(story: dict) -> str:
    return (
        str(story.get("summary_headline", "")).strip()
        or str(story.get("anchor_text", "")).strip()
        or str(story.get("subject", "")).strip()
        or str(story.get("url", "")).strip()
    )


def _normalize_story_snippet(story: dict) -> dict:
    return {
        "id": int(story.get("id", 0) or 0),
        "title": _story_title(story),
        "url": str(story.get("url", "") or ""),
        "source_name": str(story.get("source_name", "") or ""),
        "source_type": str(story.get("source_type", "") or ""),
        "published_at": story.get("published_at"),
        "effective_timestamp": str(story.get("effective_timestamp", "") or ""),
        "category": str(story.get("category", "") or ""),
        "paywall_detected": bool(story.get("paywall_detected", False)),
        "paywall_reason": story.get("paywall_reason"),
        "summary_headline": str(story.get("summary_headline", "") or ""),
        "summary_body": str(story.get("summary_body", "") or str(story.get("summary", "") or "")),
        "context": str(story.get("context", "") or ""),
    }


def _normalize_story_headline(story: dict) -> dict:
    return {
        "id": int(story.get("id", 0) or 0),
        "title": _story_title(story),
    }
