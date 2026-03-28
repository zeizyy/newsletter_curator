from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main as delivery_main
from curator.jobs import get_repository_from_config, run_daily_orchestrator_job
from tests.fakes import FakeArticleFetcher, FakeGmailService, FakeSourceFetcher, make_gmail_message
from tests.helpers import write_temp_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an offline subprocess E2E fixture for the newsletter pipeline."
    )
    parser.add_argument(
        "--scenario",
        choices=("smoke", "main_flow", "memory_stress"),
        default="main_flow",
        help="Which offline fixture scenario to run.",
    )
    parser.add_argument(
        "--max-rss-mb",
        type=float,
        default=0.0,
        help="Fail if the process max RSS exceeds this many megabytes.",
    )
    return parser.parse_args()


def _repo_root() -> Path:
    return REPO_ROOT


def _build_html_with_links(urls: list[str]) -> str:
    anchors = "\n".join(f'<a href="{url}">Story {index}</a>' for index, url in enumerate(urls, start=1))
    return f"<html><body>{anchors}</body></html>"


def _make_large_article(seed: str, *, repeat: int) -> str:
    paragraph = (
        f"{seed} explains strategy, infrastructure bottlenecks, adoption metrics, "
        "and the economics underneath the apparent headline shift. "
    )
    return (paragraph * repeat).strip()


def _build_smoke_fixture(repo_root: Path) -> tuple[FakeGmailService, FakeSourceFetcher, FakeArticleFetcher, dict]:
    now_utc = datetime.now(UTC)
    fixture_html = (repo_root / "tests" / "fixtures" / "newsletter_sample.html").read_text(
        encoding="utf-8"
    )
    service = FakeGmailService(
        messages=[
            make_gmail_message(
                message_id="gmail-smoke-1",
                subject="Infra Letter",
                from_header="Infra Letter <infra@example.com>",
                date_header=format_datetime(now_utc - timedelta(hours=2)),
                html_body=fixture_html,
            )
        ]
    )
    source_fetcher = FakeSourceFetcher(
        [
            {
                "subject": "[markets] Rates reset",
                "from": "Macro Wire",
                "source_name": "Macro Wire",
                "source_type": "additional_source",
                "date": (now_utc - timedelta(hours=1)).isoformat(),
                "published_at": (now_utc - timedelta(hours=1)).isoformat(),
                "url": "https://example.com/markets/rates-reset",
                "anchor_text": "Rates reset changes software valuations",
                "context": "Repository context for rates reset.",
            }
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            "https://example.com/markets/rates-reset": (
                "Rates reset changes software valuations and reprices future growth expectations."
            ),
            "https://example.com/ai/chips": (
                "Chip supply is tightening across cloud vendors and shifting deployment timelines."
            ),
            "https://example.com/ai/model-pricing": (
                "Open model pricing changed again and forces buyers to reconsider inference budgets."
            ),
        }
    )
    config_overrides = {
        "development": {"fake_inference": True},
        "email": {
            "digest_recipients": ["integration@example.com"],
            "digest_subject": "Offline E2E Smoke Digest",
        },
        "additional_sources": {"enabled": True},
        "limits": {
            "select_top_stories": 3,
            "final_top_stories": 3,
            "source_quotas": {"gmail": 2, "additional_source": 1},
        },
    }
    return service, source_fetcher, article_fetcher, config_overrides


def _build_memory_stress_fixture() -> tuple[FakeGmailService, FakeSourceFetcher, FakeArticleFetcher, dict]:
    now_utc = datetime.now(UTC)
    gmail_messages: list[dict] = []
    additional_stories: list[dict] = []
    articles_by_url: dict[str, str] = {}

    for message_index in range(4):
        gmail_urls = [
            f"https://example.com/gmail/story-{message_index * 2 + url_index}"
            for url_index in range(2)
        ]
        for url in gmail_urls:
            story_number = int(url.rsplit("-", 1)[1])
            articles_by_url[url] = _make_large_article(
                f"Gmail story {story_number}",
                repeat=1800,
            )
        gmail_messages.append(
            make_gmail_message(
                message_id=f"gmail-memory-{message_index}",
                subject=f"Memory Fixture {message_index}",
                from_header=f"Fixture {message_index} <fixture{message_index}@example.com>",
                date_header=format_datetime(now_utc - timedelta(hours=message_index + 1)),
                html_body=_build_html_with_links(gmail_urls),
            )
        )

    for story_index in range(8):
        url = f"https://example.com/source/story-{story_index}"
        additional_stories.append(
            {
                "subject": f"[ai] Memory fixture source story {story_index}",
                "from": "Stress Wire",
                "source_name": "Stress Wire",
                "source_type": "additional_source",
                "date": (now_utc - timedelta(minutes=story_index + 5)).isoformat(),
                "published_at": (now_utc - timedelta(minutes=story_index + 5)).isoformat(),
                "url": url,
                "anchor_text": f"Stress fixture source story {story_index}",
                "context": f"Stress fixture context {story_index}",
            }
        )
        articles_by_url[url] = _make_large_article(
            f"Additional source story {story_index}",
            repeat=1800,
        )

    config_overrides = {
        "development": {"fake_inference": True},
        "email": {
            "digest_recipients": ["loadtest@example.com"],
            "digest_subject": "Offline E2E Memory Digest",
        },
        "additional_sources": {"enabled": True},
        "limits": {
            "select_top_stories": 8,
            "final_top_stories": 8,
            "max_summary_workers": 2,
            "source_quotas": {"gmail": 4, "additional_source": 4},
        },
    }
    return (
        FakeGmailService(messages=gmail_messages),
        FakeSourceFetcher(additional_stories),
        FakeArticleFetcher(articles_by_url),
        config_overrides,
    )


def _build_main_flow_fixture() -> tuple[FakeGmailService, FakeSourceFetcher, FakeArticleFetcher, dict]:
    now_utc = datetime.now(UTC)
    gmail_urls = [
        "https://example.com/gmail/top-story",
        "https://example.com/gmail/empty-story",
        "https://example.com/gmail/backfill-story",
    ]
    gmail_service = FakeGmailService(
        messages=[
            make_gmail_message(
                message_id="gmail-main-flow-1",
                subject="Operator Flow Fixture",
                from_header="Operator Fixture <operator@example.com>",
                date_header=format_datetime(now_utc - timedelta(hours=2)),
                html_body=_build_html_with_links(gmail_urls),
            )
        ]
    )
    source_fetcher = FakeSourceFetcher(
        [
            {
                "subject": "[ai] Source-selected story",
                "from": "Signal Wire",
                "source_name": "Signal Wire",
                "source_type": "additional_source",
                "date": (now_utc - timedelta(minutes=45)).isoformat(),
                "published_at": (now_utc - timedelta(minutes=45)).isoformat(),
                "url": "https://example.com/source/selected-story",
                "anchor_text": "Source-selected story",
                "context": "Primary source story that should reach the digest.",
            },
            {
                "subject": "[ai] Duplicate story",
                "from": "Signal Wire",
                "source_name": "Signal Wire",
                "source_type": "additional_source",
                "date": (now_utc - timedelta(minutes=30)).isoformat(),
                "published_at": (now_utc - timedelta(minutes=30)).isoformat(),
                "url": "https://example.com/gmail/top-story",
                "anchor_text": "Duplicate gmail story",
                "context": "Duplicate should be removed during dedupe.",
            },
        ]
    )
    article_fetcher = FakeArticleFetcher(
        {
            "https://example.com/gmail/top-story": (
                "Top Gmail story covers product strategy, distribution leverage, and the numbers underneath adoption."
            ),
            "https://example.com/gmail/empty-story": "",
            "https://example.com/gmail/backfill-story": (
                "Backfill Gmail story provides the replacement summary after the selected story cannot be summarized."
            ),
            "https://example.com/source/selected-story": (
                "Selected source story explains the second leg of the digest and confirms cross-source delivery."
            ),
        }
    )
    config_overrides = {
        "development": {"fake_inference": True},
        "email": {
            "digest_recipients": ["mainflow@example.com"],
            "digest_subject": "Offline E2E Main Flow Digest",
        },
        "additional_sources": {"enabled": True},
        "limits": {
            "select_top_stories": 3,
            "final_top_stories": 3,
            "max_summary_workers": 1,
            "source_quotas": {"gmail": 2, "additional_source": 1},
        },
    }
    return gmail_service, source_fetcher, article_fetcher, config_overrides


def _parse_log_lines(raw_logs: str) -> list[dict]:
    parsed: list[dict] = []
    for line in raw_logs.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            parsed.append(json.loads(text))
        except json.JSONDecodeError:
            parsed.append({"raw": text})
    return parsed


def _sanitize_for_json(value, *, max_string_chars: int = 400):
    if isinstance(value, dict):
        return {key: _sanitize_for_json(item, max_string_chars=max_string_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(item, max_string_chars=max_string_chars) for item in value]
    if isinstance(value, str) and len(value) > max_string_chars:
        return f"{value[:max_string_chars]}... [truncated {len(value) - max_string_chars} chars]"
    return value


def main() -> int:
    args = parse_args()
    repo_root = _repo_root()
    fixture_builders = {
        "smoke": lambda: _build_smoke_fixture(repo_root),
        "main_flow": _build_main_flow_fixture,
        "memory_stress": _build_memory_stress_fixture,
    }
    fixture_builder = fixture_builders[args.scenario]

    with tempfile.TemporaryDirectory(prefix="curator-e2e-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        service, source_fetcher, article_fetcher, config_overrides = fixture_builder()
        config_path = write_temp_config(
            tmp_path,
            overrides={
                "database": {"path": str(tmp_path / "curator.sqlite3")},
                **config_overrides,
            },
        )
        original_config_path = delivery_main.CONFIG_PATH
        delivery_main.CONFIG_PATH = str(config_path)
        config = delivery_main.load_config()
        repository = get_repository_from_config(config)

        sent_messages: list[dict] = []

        def fake_send_email(
            service,
            to_address: str,
            subject: str,
            body: str,
            html_body: str | None = None,
        ) -> None:
            sent_messages.append(
                {
                    "to": to_address,
                    "subject": subject,
                    "body": body,
                    "html_body": html_body or "",
                }
            )

        original_send_email = delivery_main.send_email
        delivery_main.send_email = fake_send_email
        captured_stdout = io.StringIO()
        try:
            with redirect_stdout(captured_stdout):
                result = run_daily_orchestrator_job(
                    config,
                    service,
                    repository=repository,
                    source_fetcher=source_fetcher,
                    article_fetcher=article_fetcher,
                    delivery_runner_fn=delivery_main.run_job,
                )
        finally:
            delivery_main.send_email = original_send_email
            delivery_main.CONFIG_PATH = original_config_path

        stories = repository.list_stories()
        latest_delivery_run = repository.get_latest_delivery_run()
        max_rss_mb = float(result.get("runtime", {}).get("max_rss_mb_after", 0.0) or 0.0)
        budget_ok = args.max_rss_mb <= 0 or max_rss_mb <= args.max_rss_mb

        payload = {
            "scenario": args.scenario,
            "status": result.get("status"),
            "budget_ok": budget_ok,
            "max_rss_mb": max_rss_mb,
            "max_rss_budget_mb": args.max_rss_mb,
            "result": _sanitize_for_json(result),
            "sent_messages": [
                {
                    "to": item["to"],
                    "subject": item["subject"],
                    "body_preview": item["body"][:160],
                }
                for item in sent_messages
            ],
            "repository": {
                "story_count": len(stories),
                "latest_delivery_run_status": (
                    str(latest_delivery_run.get("status", "")) if latest_delivery_run else ""
                ),
                "daily_newsletter_present": latest_delivery_run is not None,
            },
            "captured_logs": _sanitize_for_json(_parse_log_lines(captured_stdout.getvalue())),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if budget_ok and result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
