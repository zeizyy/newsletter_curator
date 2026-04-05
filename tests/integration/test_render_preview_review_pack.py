from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import admin_app
from curator.jobs import get_repository_from_config
from scripts import render_preview_review_pack
from tests.helpers import create_completed_ingestion_run, write_temp_config


def test_render_preview_review_pack_writes_html_and_screenshots(tmp_path, monkeypatch, repo_root):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "email": {
                "digest_recipients": ["review@example.com"],
                "digest_subject": "Review Pack Digest",
            },
            "additional_sources": {"enabled": True, "hours": 48},
            "limits": {
                "select_top_stories": 2,
                "final_top_stories": 2,
                "source_quotas": {"gmail": 0, "additional_source": 2},
            },
        },
    )
    monkeypatch.setenv("CURATOR_PUBLIC_BASE_URL", "http://curator.test")
    admin_app.CONFIG_PATH = str(config_path)
    repository = get_repository_from_config(render_preview_review_pack.config_module.load_config(config_path))
    newsletter_date = dt.datetime.now(dt.UTC).date().isoformat()
    ingestion_run_id = create_completed_ingestion_run(repository, "additional_source")

    story_id = repository.upsert_story(
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
        story_id,
        "Rates reset changes software valuations and reprices growth names.",
        summary_headline="Rates reset changes software valuations",
        summary_body="Key takeaways\n- Rates reset changes software valuations.\n\nWhy this matters to me\nThis matters for software multiples.",
        summary_model="gpt-5-mini",
        summarized_at="2026-03-24T08:00:00+00:00",
    )
    newsletter_id = repository.upsert_daily_newsletter(
        newsletter_date=newsletter_date,
        subject="Review Pack Digest",
        body="Review pack digest body",
        html_body="<html><body>email-safe placeholder</body></html>",
        selected_items=[
            {
                "title": "Rates reset changes software valuations",
                "url": "https://example.com/markets/rates-reset",
            }
        ],
        metadata={"render_groups": {}},
        content={
            "version": 1,
            "render_groups": {
                "Markets / stocks / macro / economy": [
                    {
                        "title": "Rates reset changes software valuations",
                        "url": "https://example.com/markets/rates-reset",
                        "body": "Key takeaways\n- Rates reset changes software valuations.\n\nWhy this matters to me\nThis matters for software multiples.",
                        "source_name": "Macro Wire",
                        "published_at": "2026-03-24T07:30:00+00:00",
                        "display_timestamp": "Mar 24, 12:30 AM PT",
                        "timestamp_iso": "2026-03-24T07:30:00+00:00",
                    }
                ]
            },
            "ranked_candidates": 1,
            "selected": 1,
            "accepted_items": 1,
        },
    )
    repository.ensure_newsletter_open_token(newsletter_id)
    repository.ensure_tracked_links(
        newsletter_id,
        [
            {
                "title": "Rates reset changes software valuations",
                "url": "https://example.com/markets/rates-reset",
            }
        ],
    )

    output_dir = tmp_path / "review-pack"

    def fake_run(cmd, check, capture_output, text):
        assert cmd[:2] == ["qlmanage", "-t"]
        assert "-o" in cmd
        screen_dir = Path(cmd[cmd.index("-o") + 1])
        html_paths = [Path(value) for value in cmd if value.endswith(".html")]
        screen_dir.mkdir(parents=True, exist_ok=True)
        for html_path in html_paths:
            (screen_dir / f"{html_path.name}.png").write_text("fake-png", encoding="utf-8")
        class Result:
            stdout = "ok"
            stderr = ""
        return Result()

    monkeypatch.setattr(render_preview_review_pack.subprocess, "run", fake_run)
    stdout = io.StringIO()
    monkeypatch.setattr(
        render_preview_review_pack,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "config_path": config_path,
                "output_dir": output_dir,
                "newsletter_date": newsletter_date,
                "include_admin_surfaces": True,
                "thumbnail_size": 1600,
            },
        )(),
    )
    monkeypatch.setattr("sys.stdout", stdout)

    render_preview_review_pack.main()

    expected_html = [
        output_dir / "admin_config.html",
        output_dir / "admin_analytics.html",
        output_dir / "admin_preview.html",
        output_dir / "digest_market_tape.html",
        output_dir / "digest_email_safe.html",
    ]
    for path in expected_html:
        assert path.exists()

    expected_png = [
        output_dir / "screens" / "admin_config.html.png",
        output_dir / "screens" / "admin_analytics.html.png",
        output_dir / "screens" / "admin_preview.html.png",
        output_dir / "screens" / "digest_market_tape.html.png",
        output_dir / "screens" / "digest_email_safe.html.png",
    ]
    for path in expected_png:
        assert path.exists()

    assert "Review pack output:" in stdout.getvalue()
    assert str(output_dir) in stdout.getvalue()
