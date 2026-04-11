from __future__ import annotations

import threading
import time

from curator.config import load_config
from curator.content import extract_links_from_html
from curator.gmail import collect_live_gmail_links
from tests.fakes import FakeGmailService, make_gmail_message
from tests.helpers import write_temp_config


def test_fetch_gmail_message_collection_runs_concurrently(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "limits": {
                "max_links_per_email": 2,
                "max_gmail_message_workers": 2,
            },
        },
    )
    service = FakeGmailService(
        messages=[
            make_gmail_message(
                message_id=f"msg-{index}",
                subject=f"Newsletter {index}",
                from_header=f"Source {index} <source-{index}@example.com>",
                date_header=f"Mon, 23 Mar 2026 1{index}:00:00 +0000",
                html_body=(
                    "<html><body>"
                    f'<a href="https://example.com/story-{index}">Story {index}</a>'
                    "</body></html>"
                ),
            )
            for index in range(1, 5)
        ]
    )
    config = load_config(str(config_path))

    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def slow_get_message(service, message_id: str):
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        try:
            return service.users().messages().get(userId="me", id=message_id, format="full").execute()
        finally:
            with active_lock:
                active -= 1

    links = collect_live_gmail_links(
        service,
        config,
        get_message_fn=slow_get_message,
        extract_links_from_html_fn=extract_links_from_html,
    )

    assert max_active == 2
    assert [link["url"] for link in links] == [
        "https://example.com/story-1",
        "https://example.com/story-2",
        "https://example.com/story-3",
        "https://example.com/story-4",
    ]
