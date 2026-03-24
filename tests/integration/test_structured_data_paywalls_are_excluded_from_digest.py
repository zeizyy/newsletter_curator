from __future__ import annotations

import importlib

from curator.content import extract_article_details_from_html
from curator.jobs import get_repository_from_config, run_fetch_sources_job
from tests.fakes import FakeOpenAI, FakeSourceFetcher
from tests.helpers import write_temp_config


def test_structured_data_paywalls_are_excluded_from_digest(monkeypatch, tmp_path):
    main = importlib.import_module("main")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3"), "ttl_days": 7},
            "development": {"fake_inference": True},
            "email": {
                "digest_recipients": ["structured@example.com"],
                "digest_subject": "Structured Paywall Digest",
            },
            "additional_sources": {"enabled": True, "hours": 48},
            "limits": {
                "select_top_stories": 2,
                "final_top_stories": 2,
                "source_quotas": {"gmail": 0, "additional_source": 2},
            },
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    source_fetcher = FakeSourceFetcher(
        [
            {
                "subject": "[markets] Public article",
                "from": "Open Wire",
                "source_name": "Open Wire",
                "source_type": "additional_source",
                "date": "2026-03-24T07:30:00+00:00",
                "url": "https://example.com/markets/public-article",
                "anchor_text": "Public article",
                "context": "Open article context",
                "category": "Markets / stocks / macro / economy",
            },
            {
                "subject": "[media] Metered article",
                "from": "Metered Wire",
                "source_name": "Metered Wire",
                "source_type": "additional_source",
                "date": "2026-03-24T06:00:00+00:00",
                "url": "https://example.com/media/metered-article",
                "anchor_text": "Metered article",
                "context": "Metered article context",
                "category": "Tech blogs",
            },
        ]
    )

    public_html = """
    <html>
      <head>
        <title>Public article</title>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"NewsArticle","headline":"Public article","isAccessibleForFree":true}
        </script>
      </head>
      <body>
        <article>
          <p>Public article text with enough depth to be servable and useful for a digest.</p>
        </article>
      </body>
    </html>
    """
    metered_html = """
    <html>
      <head>
        <title>Metered article</title>
        <script type="application/ld+json">
        {
          "@context":"https://schema.org",
          "@type":"NewsArticle",
          "headline":"Metered article",
          "isAccessibleForFree":false,
          "hasPart":{"@type":"WebPageElement","isAccessibleForFree":false,"cssSelector":".paywall"}
        }
        </script>
      </head>
      <body>
        <article>
          <p>Teaser paragraph visible before the paywall.</p>
        </article>
        <div class="paywall">Subscribe to continue reading this article.</div>
      </body>
    </html>
    """

    html_by_url = {
        "https://example.com/markets/public-article": public_html,
        "https://example.com/media/metered-article": metered_html,
    }

    def article_fetcher(url: str, max_article_chars: int, timeout: int = 25, retries: int = 3):
        return extract_article_details_from_html(
            html_by_url[url],
            url=url,
            max_article_chars=max_article_chars,
        )

    fetch_result = run_fetch_sources_job(
        config,
        source_fetcher=source_fetcher,
        article_fetcher=article_fetcher,
    )
    repository = get_repository_from_config(config)
    stories = repository.list_stories(source_type="additional_source")
    visible_stories = repository.list_stories(
        source_type="additional_source",
        include_paywalled=False,
        require_summary=True,
    )

    monkeypatch.setattr(main, "OpenAI", FakeOpenAI)
    preview_result = main.preview_job(config)

    assert fetch_result["status"] == "completed"
    assert fetch_result["paywall_stories"] == 1
    assert len(stories) == 2
    assert len(visible_stories) == 1
    assert visible_stories[0]["source_name"] == "Open Wire"
    assert preview_result["status"] == "completed"
    assert preview_result["accepted_items"] == 1
    assert "Public article" in preview_result["preview"]["body"]
    assert "Metered article" not in preview_result["preview"]["body"]
