#!/usr/bin/env python3
"""
Fetch RSS/Atom feeds and build a category-balanced daily digest.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import datetime as dt
import email.utils
import hashlib
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse


DEFAULT_FEEDS: dict[str, list[dict[str, str]]] = {
    "ai": [
        {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml"},
        {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/"},
        {"name": "Google Research Blog", "url": "https://research.google/blog/rss/"},
        {"name": "Microsoft AI Blog", "url": "https://blogs.microsoft.com/ai/feed/"},
        {
            "name": "MIT Technology Review AI",
            "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
        },
        {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml"},
    ],
    "markets": [
        {"name": "Financial Times Markets", "url": "https://www.ft.com/markets?format=rss"},
        {"name": "Financial Times Technology", "url": "https://www.ft.com/technology?format=rss"},
        {"name": "Sherwood", "url": "https://www.sherwood.news/rss.xml"},
        {"name": "NYT Technology", "url": "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml"},
    ],
    "top-news": [
        {"name": "NYTimes Home", "url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"},
        {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
        {"name": "CNN Top Stories", "url": "http://rss.cnn.com/rss/edition.rss"},
        {"name": "NPR News", "url": "https://feeds.npr.org/1001/rss.xml"},
        {"name": "Economist World This Week", "url": "https://www.economist.com/the-world-this-week/rss.xml"},
    ],
}

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


@dataclass
class Story:
    category: str
    source: str
    title: str
    url: str
    published_at: dt.datetime
    summary: str


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
    ]
    cleaned = parsed._replace(query=urlencode(query, doseq=True), fragment="")
    return urlunparse(cleaned)


def parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None

    parsed = email.utils.parsedate_to_datetime(value)
    if parsed:
        return parsed.astimezone(dt.timezone.utc)

    iso = value.replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(iso).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def text_or_empty(node: ET.Element | None, tag: str) -> str:
    if node is None:
        return ""
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def find_text_by_local_names(node: ET.Element, names: list[str]) -> str:
    wanted = {name.lower() for name in names}
    for child in list(node):
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in wanted and child.text:
            value = child.text.strip()
            if value:
                return value
    return ""


def find_link_by_local_names(node: ET.Element, names: list[str]) -> str:
    wanted = {name.lower() for name in names}
    for child in list(node):
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in wanted:
            href = (child.attrib.get("href") or "").strip()
            if href:
                return href
            if child.text and child.text.strip():
                return child.text.strip()
    return ""


def fetch_xml(url: str, timeout: int = 20, max_redirects: int = 5) -> bytes:
    headers = {
        "User-Agent": "daily-news-curator/1.0",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
    }
    context = ssl.create_default_context()
    current_url = url
    for _ in range(max_redirects + 1):
        req = urllib.request.Request(url=current_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                if not location:
                    raise
                current_url = urljoin(current_url, location)
                continue
            raise
    raise RuntimeError(f"too many redirects while fetching: {url}")


def parse_rss(root: ET.Element, category: str, source_name: str) -> list[Story]:
    channel = root.find("channel")
    if channel is None:
        return []
    stories: list[Story] = []
    for item in channel.findall("item"):
        title = text_or_empty(item, "title") or find_text_by_local_names(item, ["title"])
        url = text_or_empty(item, "link") or find_link_by_local_names(item, ["link"])
        summary = text_or_empty(item, "description") or find_text_by_local_names(
            item, ["description", "content", "encoded"]
        )
        published_raw = (
            text_or_empty(item, "pubDate")
            or find_text_by_local_names(item, ["pubdate", "date", "published", "updated"])
        )
        published_at = parse_datetime(published_raw)
        if not title or not url:
            continue
        if not published_at:
            continue
        stories.append(
            Story(
                category=category,
                source=source_name,
                title=title,
                url=canonicalize_url(url),
                published_at=published_at,
                summary=summary,
            )
        )
    return stories


def parse_atom(root: ET.Element, category: str, source_name: str) -> list[Story]:
    stories: list[Story] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title = (entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
        summary = (
            entry.findtext("atom:summary", default="", namespaces=ATOM_NS)
            or entry.findtext("atom:content", default="", namespaces=ATOM_NS)
            or ""
        ).strip()
        published_raw = (
            entry.findtext("atom:published", default="", namespaces=ATOM_NS)
            or entry.findtext("atom:updated", default="", namespaces=ATOM_NS)
            or find_text_by_local_names(entry, ["published", "updated"])
        )
        published_at = parse_datetime(published_raw)

        url = ""
        for link in entry.findall("atom:link", ATOM_NS):
            rel = (link.attrib.get("rel") or "alternate").lower()
            href = (link.attrib.get("href") or "").strip()
            if rel == "alternate" and href:
                url = href
                break
            if not url and href:
                url = href

        if not title or not url:
            continue
        if not published_at:
            continue
        stories.append(
            Story(
                category=category,
                source=source_name,
                title=title,
                url=canonicalize_url(url),
                published_at=published_at,
                summary=summary,
            )
        )
    return stories


def parse_feed(xml_bytes: bytes, category: str, source_name: str) -> list[Story]:
    root = ET.fromstring(xml_bytes)
    tag = root.tag.lower()
    if tag.endswith("rss") or tag.endswith("rdf"):
        return parse_rss(root, category, source_name)
    if tag.endswith("feed"):
        return parse_atom(root, category, source_name)
    return []


def load_feeds(path: str | None) -> dict[str, list[dict[str, str]]]:
    if not path:
        return DEFAULT_FEEDS
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("feeds file must be a JSON object keyed by category")
    parsed: dict[str, list[dict[str, str]]] = {}
    for category, sources in data.items():
        if not isinstance(category, str) or not isinstance(sources, list):
            continue
        clean_sources: list[dict[str, str]] = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            name = str(source.get("name", "")).strip()
            url = str(source.get("url", "")).strip()
            if name and url:
                clean_sources.append({"name": name, "url": url})
        if clean_sources:
            parsed[category] = clean_sources
    if not parsed:
        raise ValueError("no valid feeds found in feeds file")
    return parsed


def digest_id(story: Story) -> str:
    raw = f"{story.category}|{story.source}|{story.url}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:12]


def dedupe_and_filter(stories: list[Story], hours: int) -> list[Story]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    seen: set[str] = set()
    result: list[Story] = []
    for story in sorted(stories, key=lambda s: s.published_at, reverse=True):
        if story.published_at < cutoff:
            continue
        key = story.url
        if key in seen:
            continue
        seen.add(key)
        result.append(story)
    return result


def pick_balanced(stories: list[Story], top_per_category: int, max_total: int) -> list[Story]:
    grouped: dict[str, list[Story]] = {}
    for story in stories:
        grouped.setdefault(story.category, []).append(story)

    result: list[Story] = []
    for category in sorted(grouped.keys()):
        result.extend(grouped[category][:top_per_category])

    result.sort(key=lambda s: s.published_at, reverse=True)
    return result[:max_total]


def render_markdown(stories: list[Story]) -> str:
    grouped: dict[str, list[Story]] = {}
    for story in stories:
        grouped.setdefault(story.category, []).append(story)

    lines = ["# Daily News Digest", ""]
    for category in sorted(grouped.keys()):
        lines.append(f"## {category}")
        lines.append("")
        for story in grouped[category]:
            ts = story.published_at.strftime("%Y-%m-%d %H:%M UTC")
            one_line = story.summary.splitlines()[0].strip() if story.summary else ""
            lines.append(f"- **{story.title}**")
            lines.append(f"  - Source: {story.source}")
            lines.append(f"  - Published: {ts}")
            lines.append(f"  - URL: {story.url}")
            lines.append(f"  - Why it matters: {one_line or 'Add a one-line summary.'}")
            lines.append(f"  - ID: `{digest_id(story)}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_json(stories: list[Story]) -> str:
    payload: list[dict[str, Any]] = []
    for story in stories:
        payload.append(
            {
                "id": digest_id(story),
                "category": story.category,
                "title": story.title,
                "source": story.source,
                "url": story.url,
                "published_at": story.published_at.isoformat(),
                "summary": story.summary,
            }
        )
    return json.dumps(payload, indent=2)


def _emit_event(
    event_logger: Callable[..., None] | None,
    event: str,
    /,
    **payload,
) -> None:
    if event_logger is None:
        return
    event_logger(event, **payload)


def build_daily_digest_payload(
    *,
    feeds_file: str | None = None,
    hours: int = 24,
    top_per_category: int = 5,
    max_total: int = 20,
    fetch_timeout_seconds: int = 20,
    max_redirects: int = 5,
    total_timeout_seconds: int | None = None,
    event_logger: Callable[..., None] | None = None,
    fetch_xml_fn=fetch_xml,
) -> dict[str, Any]:
    feed_map = load_feeds(feeds_file)
    total_feeds = sum(len(sources) for sources in feed_map.values())
    started_at = time.monotonic()
    _emit_event(
        event_logger,
        "additional_source_digest_started",
        total_feeds=total_feeds,
        category_count=len(feed_map),
        hours=hours,
        top_per_category=top_per_category,
        max_total=max_total,
        fetch_timeout_seconds=fetch_timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
        custom_feeds=bool(feeds_file),
    )

    stories: list[Story] = []
    failures: list[str] = []
    feed_index = 0
    for category, sources in feed_map.items():
        for source in sources:
            feed_index += 1
            name = source["name"]
            url = source["url"]
            remaining_budget_seconds: float | None = None
            if total_timeout_seconds is not None:
                remaining_budget_seconds = total_timeout_seconds - (time.monotonic() - started_at)
                if remaining_budget_seconds <= 0:
                    _emit_event(
                        event_logger,
                        "additional_source_digest_timed_out",
                        feed_index=feed_index,
                        total_feeds=total_feeds,
                        category=category,
                        source_name=name,
                        url=url,
                        elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
                    )
                    raise TimeoutError(
                        f"Additional source collection exceeded {total_timeout_seconds} seconds."
                    )
            effective_timeout = float(fetch_timeout_seconds)
            if remaining_budget_seconds is not None:
                effective_timeout = max(0.1, min(effective_timeout, remaining_budget_seconds))
            feed_started_at = time.monotonic()
            _emit_event(
                event_logger,
                "additional_source_feed_started",
                feed_index=feed_index,
                total_feeds=total_feeds,
                category=category,
                source_name=name,
                url=url,
                timeout_seconds=round(effective_timeout, 3),
                remaining_budget_seconds=(
                    round(remaining_budget_seconds, 3)
                    if remaining_budget_seconds is not None
                    else None
                ),
            )
            try:
                raw = fetch_xml_fn(
                    url,
                    timeout=effective_timeout,
                    max_redirects=max_redirects,
                )
                parsed = parse_feed(raw, category=category, source_name=name)
                stories.extend(parsed)
                _emit_event(
                    event_logger,
                    "additional_source_feed_completed",
                    feed_index=feed_index,
                    total_feeds=total_feeds,
                    category=category,
                    source_name=name,
                    url=url,
                    response_bytes=len(raw),
                    parsed_story_count=len(parsed),
                    duration_ms=round((time.monotonic() - feed_started_at) * 1000, 2),
                )
            except Exception as exc:
                failures.append(f"{name} ({url}): {exc}")
                _emit_event(
                    event_logger,
                    "additional_source_feed_failed",
                    feed_index=feed_index,
                    total_feeds=total_feeds,
                    category=category,
                    source_name=name,
                    url=url,
                    error=str(exc),
                    error_type=exc.__class__.__name__,
                    duration_ms=round((time.monotonic() - feed_started_at) * 1000, 2),
                )

    selected = pick_balanced(
        dedupe_and_filter(stories, hours=hours),
        top_per_category=top_per_category,
        max_total=max_total,
    )
    _emit_event(
        event_logger,
        "additional_source_digest_completed",
        total_feeds=total_feeds,
        story_count=len(stories),
        selected_count=len(selected),
        failure_count=len(failures),
        elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
    )
    return {
        "stories": selected,
        "failures": failures,
        "total_feeds": total_feeds,
        "story_count": len(stories),
        "selected_count": len(selected),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a daily digest from RSS/Atom feeds.")
    parser.add_argument("--feeds-file", help="Path to JSON feeds map. If omitted, use built-in defaults.")
    parser.add_argument("--hours", type=int, default=24, help="Recency window in hours (default: 24).")
    parser.add_argument("--top-per-category", type=int, default=5, help="Max items per category.")
    parser.add_argument("--max-total", type=int, default=20, help="Max items in final digest.")
    parser.add_argument("--output", choices=["markdown", "json"], default="markdown")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = build_daily_digest_payload(
            feeds_file=args.feeds_file,
            hours=args.hours,
            top_per_category=args.top_per_category,
            max_total=args.max_total,
        )
    except Exception as exc:
        print(f"Failed to build digest: {exc}", file=sys.stderr)
        return 1

    selected = result["stories"]
    failures = result["failures"]

    if args.output == "json":
        print(render_json(selected))
    else:
        print(render_markdown(selected))

    if failures:
        print("\n# Feed Errors", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
