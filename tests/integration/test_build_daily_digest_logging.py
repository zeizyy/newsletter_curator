from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
import sys
import threading
import time


def _load_build_daily_digest_module(repo_root):
    script_path = repo_root / "skills" / "daily-news-curator" / "scripts" / "build_daily_digest.py"
    spec = importlib.util.spec_from_file_location("build_daily_digest_test_module", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_daily_digest_emits_feed_progress_events(repo_root, tmp_path):
    module = _load_build_daily_digest_module(repo_root)
    feeds_path = tmp_path / "feeds.json"
    feeds_path.write_text(
        json.dumps(
            {
                "ai": [
                    {
                        "name": "Example Feed",
                        "url": "https://example.com/rss.xml",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    recent_pub_date = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>Story One</title>
      <link>https://example.com/story-one?utm_source=test</link>
      <description>Important context for the story.</description>
      <pubDate>{recent_pub_date}</pubDate>
    </item>
  </channel>
</rss>
""".encode("utf-8")
    captured_events: list[tuple[str, dict]] = []

    result = module.build_daily_digest_payload(
        feeds_file=str(feeds_path),
        hours=48,
        top_per_category=5,
        max_total=10,
        event_logger=lambda event, **payload: captured_events.append((event, payload)),
        fetch_xml_fn=lambda url, timeout=20, max_redirects=5: rss,
    )

    assert result["selected_count"] == 1
    assert [event for event, _payload in captured_events] == [
        "additional_source_digest_started",
        "additional_source_feed_started",
        "additional_source_feed_completed",
        "additional_source_digest_completed",
    ]
    assert captured_events[1][1]["source_name"] == "Example Feed"
    assert captured_events[2][1]["parsed_story_count"] == 1
    assert captured_events[3][1]["selected_count"] == 1


def test_build_daily_digest_fetches_feeds_concurrently(repo_root, tmp_path):
    module = _load_build_daily_digest_module(repo_root)
    feeds_path = tmp_path / "feeds.json"
    feeds_path.write_text(
        json.dumps(
            {
                "ai": [
                    {"name": "Feed One", "url": "https://example.com/feed-1.xml"},
                    {"name": "Feed Two", "url": "https://example.com/feed-2.xml"},
                    {"name": "Feed Three", "url": "https://example.com/feed-3.xml"},
                    {"name": "Feed Four", "url": "https://example.com/feed-4.xml"},
                ]
            }
        ),
        encoding="utf-8",
    )

    recent_pub_date = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def slow_fetch_xml(url, timeout=20, max_redirects=5):
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        try:
            story_slug = url.rsplit("/", 1)[-1].replace(".xml", "")
            return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>{story_slug}</title>
      <link>https://example.com/{story_slug}</link>
      <description>Important context for the story.</description>
      <pubDate>{recent_pub_date}</pubDate>
    </item>
  </channel>
</rss>
""".encode("utf-8")
        finally:
            with active_lock:
                active -= 1

    result = module.build_daily_digest_payload(
        feeds_file=str(feeds_path),
        hours=48,
        top_per_category=5,
        max_total=10,
        max_feed_workers=2,
        fetch_xml_fn=slow_fetch_xml,
    )

    assert result["selected_count"] == 4
    assert max_active == 2
