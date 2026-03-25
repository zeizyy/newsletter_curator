from __future__ import annotations

from curator.config import load_config
from curator.jobs import get_repository_from_config, run_fetch_gmail_job
from tests.fakes import FakeArticleFetcher, FakeGmailService, make_gmail_message
from tests.helpers import write_temp_config


def test_gmail_prefetch_scoring_limits_article_fetches(tmp_path):
    html_body = "<html><body>" + "".join(
        (
            f'<p>Context {index} <a href="https://example.com/story-{index:02d}">'
            f"Story {index:02d}</a></p>"
        )
        for index in range(1, 21)
    ) + "</body></html>"

    service = FakeGmailService(
        messages=[
            make_gmail_message(
                message_id="msg-1",
                subject="Daily Macro Notes",
                from_header="Macro Letter <macro@example.com>",
                date_header="Tue, 24 Mar 2026 14:00:00 +0000",
                html_body=html_body,
            )
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            f"https://example.com/story-{index:02d}": (
                f"Story {index:02d} article text with enough detail to summarize deterministically."
            )
            for index in range(1, 21)
        }
    )

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "development": {"fake_inference": True},
            "additional_sources": {"enabled": False},
            "limits": {
                "max_links_per_email": 20,
                "max_gmail_fetch_after_score": 15,
                "max_ingest_summaries": 10,
            },
        },
    )
    config = load_config(str(config_path))

    result = run_fetch_gmail_job(config, service, article_fetcher=article_fetcher)
    repository = get_repository_from_config(config)
    stories = repository.list_stories(source_type="gmail")

    assert result["status"] == "completed"
    assert result["stories_seen"] == 20
    assert result["stories_selected_for_fetch"] == 15
    assert len(article_fetcher.calls) == 15
    assert len(stories) == 15
    assert "https://example.com/story-16" not in {story["url"] for story in stories}

