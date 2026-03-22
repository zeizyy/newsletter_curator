from __future__ import annotations

import importlib

from curator.jobs import get_repository_from_config, run_fetch_gmail_job
from tests.fakes import FakeGmailService, make_gmail_message
from tests.helpers import write_temp_config


def test_title_extraction_avoids_generic_read_more_titles(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    admin_app = importlib.import_module("admin_app")

    gmail_html = """
    <html>
      <body>
        <p>
          Jensen Huang put Nvidia's Blackwell and Vera Rubin sales projections into the $1 trillion stratosphere.
          <a href="https://example.com/nvidia/blackwell">Read More</a>
        </p>
        <p>
          The Gemini-powered features in Google Workspace that are worth using.
          <a href="https://example.com/google/workspace-gemini">Read More</a>
        </p>
      </body>
    </html>
    """
    service = FakeGmailService(
        messages=[
            make_gmail_message(
                message_id="msg-1",
                subject="TechCrunch Week in Review",
                from_header="TechCrunch Week in Review <newsletters@techcrunch.com>",
                date_header="Sat, 21 Mar 2026 15:00:17 +0000",
                html_body=gmail_html,
            )
        ]
    )

    article_details_by_url = {
        "https://example.com/nvidia/blackwell": {
            "article_text": "Nvidia's Blackwell and Vera Rubin roadmap pushes projected system demand toward the trillion-dollar mark.",
            "document_title": "Nvidia's Blackwell and Vera Rubin roadmap pushes demand toward $1 trillion",
            "document_excerpt": "Nvidia's roadmap update ties AI infrastructure demand to unusually large forward revenue expectations.",
        },
        "https://example.com/google/workspace-gemini": {
            "article_text": "Google Workspace is shipping Gemini-powered drafting, summarization, and spreadsheet assistance features.",
            "document_title": "The Gemini-powered Google Workspace features actually worth using",
            "document_excerpt": "Google is threading Gemini into everyday productivity workflows instead of just shipping a chatbot tab.",
        },
    }

    def article_fetcher(url: str, max_article_chars: int, timeout: int = 25, retries: int = 3):
        details = dict(article_details_by_url[url])
        details["article_text"] = details["article_text"][:max_article_chars]
        return details

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "additional_sources": {"enabled": False},
            "development": {"fake_inference": True},
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(admin_app, "CONFIG_PATH", str(config_path))
    config = main.load_config()

    result = run_fetch_gmail_job(config, service, article_fetcher=article_fetcher)
    repository = get_repository_from_config(config)
    stories = repository.list_stories(source_type="gmail")

    assert result["status"] == "completed"
    assert len(stories) == 2
    titles = {story["anchor_text"] for story in stories}
    assert "Read More" not in titles
    assert "Nvidia's Blackwell and Vera Rubin roadmap pushes demand toward $1 trillion" in titles
    assert "The Gemini-powered Google Workspace features actually worth using" in titles

    client = admin_app.app.test_client()
    response = client.get("/stories?source_type=gmail")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Nvidia&#39;s Blackwell and Vera Rubin roadmap pushes demand toward $1 trillion" in page
    assert "The Gemini-powered Google Workspace features actually worth using" in page
    assert ">Read More<" not in page
