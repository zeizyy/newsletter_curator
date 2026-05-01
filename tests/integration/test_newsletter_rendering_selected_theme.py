from __future__ import annotations

import importlib
from datetime import UTC, datetime

from curator.jobs import get_repository_from_config
from tests.fakes import FakeOpenAI
from tests.helpers import create_completed_ingestion_run, write_temp_config


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 24, 18, 0, 0, tzinfo=tz or UTC)


def test_selected_theme_renders_ai_signal_daily_without_extra_hero_chrome(monkeypatch, tmp_path):
    main = importlib.import_module("main")
    jobs = importlib.import_module("curator.jobs")
    rendering = importlib.import_module("curator.rendering")
    sources = importlib.import_module("curator.sources")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["preview@example.com"],
                "digest_subject": "Theme Digest",
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
    monkeypatch.setattr(jobs, "datetime", FixedDateTime)
    monkeypatch.setattr(rendering, "datetime", FixedDateTime)
    monkeypatch.setattr(sources, "datetime", FixedDateTime)
    config = main.load_config()

    repository = get_repository_from_config(config)
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")

    first_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Macro Wire",
            "subject": "[markets] Rates reset",
            "url": "https://example.com/markets/rates-reset",
            "anchor_text": "Rates reset changes software valuations",
            "context": "Repository context for rates reset",
            "category": "Markets / stocks / macro / economy",
            "published_at": "2026-03-24T07:30:00+00:00",
            "summary": "Rates reset summary",
        },
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_article_snapshot(
        first_story_id,
        "Rates reset changes software valuations and reprices growth names.",
        summary_headline="Rates reset changes software valuations",
        summary_body="Key takeaways\n- Rates reset changes software valuations.\n\nWhy this matters to me\nThis matters for software multiples.",
        summary_model="gpt-5-mini",
        summarized_at="2026-03-24T08:00:00+00:00",
    )

    second_story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "AI Wire",
            "subject": "[ai] Open model pricing changed",
            "url": "https://example.com/ai/model-pricing",
            "anchor_text": "Open model pricing changed",
            "context": "Repository context for pricing",
            "category": "AI & ML industry developments",
            "published_at": "2026-03-24T06:00:00+00:00",
            "summary": "Pricing summary",
        },
        ingestion_run_id=ingestion_run_id,
    )
    repository.upsert_article_snapshot(
        second_story_id,
        "Open model pricing changed and pushes buyers to recalculate inference budgets.",
        summary_headline="Open model pricing changed",
        summary_body="Key takeaways\n- Open model pricing changed.\n\nWhy this matters to me\nThis matters for inference budgets.",
        summary_model="gpt-5-mini",
        summarized_at="2026-03-24T08:05:00+00:00",
    )

    fake_openai = FakeOpenAI()
    monkeypatch.setattr(main, "OpenAI", lambda: fake_openai)

    result = main.preview_job(config)

    assert result["status"] == "completed"
    assert result["preview"] is not None
    html = result["preview"]["html_body"]
    assert "March 24, 2026" in html
    assert "AI Signal Daily" in html
    assert "Your highest-signal daily briefing." in html
    assert "Operator Edition" not in html
    assert "Daily Briefing" not in html
    assert "stories selected" not in html
    assert "Read original" in html
    assert "1 min read" in html
    assert 'target="_blank"' in html
    assert "Mar 24, 12:30 AM PT" in html
    assert "Financial Times" not in html
    assert 'role="presentation"' in html
    assert "max-width:640px" in html

    stored_newsletter = repository.get_daily_newsletter("2026-03-24")
    assert stored_newsletter is not None
    render_groups = stored_newsletter["content"]["render_groups"]
    assert render_groups[0]["read_time_minutes"] == 1
    assert render_groups[0]["read_time_label"] == "1 min read"

    web_html = rendering.render_digest_html(render_groups)
    assert 'class="story-read-time"' in web_html
    assert "1 min read" in web_html
