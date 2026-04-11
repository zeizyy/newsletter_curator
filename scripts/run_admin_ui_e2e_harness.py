from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from curator import config as config_module
from curator.jobs import get_repository_from_config
from curator.repository import SQLiteRepository
from tests.helpers import create_completed_ingestion_run, write_temp_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a browser-driven admin/subscriber E2E harness against a seeded local admin app "
            "and write screenshots plus a JSON manifest."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "output" / "playwright" / "admin-ui-e2e",
        help="Directory for screenshots, server logs, and the manifest.",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=None,
        help="Optional directory for the seeded config/database fixture. Defaults to a temp dir.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for the local admin server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8091,
        help="Port for the local admin server.",
    )
    parser.add_argument(
        "--admin-token",
        default="local-review-token",
        help="Admin token used for the operator journey.",
    )
    parser.add_argument(
        "--subscriber-email",
        default="existing@example.com",
        help="Seeded subscriber email used for the login/settings journey.",
    )
    parser.add_argument(
        "--updated-persona",
        default="Focus on chips, software margins, and rates.",
        help="Persona text saved during the settings step.",
    )
    parser.add_argument(
        "--public-base-url",
        default="",
        help=(
            "Absolute base URL the app should use when it generates subscriber login links. "
            "Defaults to the local harness origin."
        ),
    )
    return parser.parse_args()


@contextmanager
def fixture_root_context(explicit_path: Path | None):
    if explicit_path is not None:
        explicit_path.mkdir(parents=True, exist_ok=True)
        yield explicit_path
        return
    with tempfile.TemporaryDirectory(prefix="curator-admin-ui-e2e-") as tmp_dir:
        yield Path(tmp_dir)


def resolve_pwcli_path() -> Path:
    configured = str(os.environ.get("PWCLI", "")).strip()
    if configured:
        return Path(configured)
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    return codex_home / "skills" / "playwright" / "scripts" / "playwright_cli.sh"


def seed_review_fixture(
    root: Path,
    *,
    host: str,
    port: int,
    public_base_url: str,
    subscriber_email: str,
) -> dict:
    config_path = write_temp_config(
        root,
        overrides={
            "database": {"path": str(root / "curator.sqlite3")},
            "email": {
                "digest_recipients": [subscriber_email],
                "digest_subject": "AI Signal Daily",
            },
            "additional_sources": {
                "enabled": True,
                "hours": 48,
                "feeds_file": "tests/fixtures/additional_sources_feeds.txt",
            },
            "limits": {
                "select_top_stories": 20,
                "final_top_stories": 6,
                "source_quotas": {"gmail": 2, "additional_source": 4},
            },
            "persona": {"text": "Default persona for fallback testing."},
            "tracking": {"enabled": False},
        },
    )
    config = config_module.load_config(config_path)
    repository = get_repository_from_config(config)
    if repository is None:
        raise RuntimeError("Failed to initialize the seeded SQLite repository.")

    macro_id = repository.upsert_source(source_type="additional_source", source_name="Macro Wire")
    ai_id = repository.upsert_source(source_type="additional_source", source_name="AI Wire")
    signal_id = repository.upsert_source(source_type="gmail", source_name="Signal Mail")
    chip_id = repository.upsert_source(source_type="additional_source", source_name="Chip Insider")
    repository.set_source_selection_by_id(macro_id, enabled=True)
    repository.set_source_selection_by_id(ai_id, enabled=False)
    repository.set_source_selection_by_id(signal_id, enabled=True)
    repository.set_source_selection_by_id(chip_id, enabled=True)

    subscriber = repository.upsert_subscriber(subscriber_email)
    repository.upsert_subscriber_profile(
        int(subscriber["id"]),
        persona_text="Focus on semis, software margins, and bond yields.",
        preferred_sources=["Macro Wire", "AI Wire"],
    )

    recent_story_time = datetime.now(UTC) - timedelta(hours=2)
    recent_story_time_iso = recent_story_time.isoformat()
    recent_summary_time_iso = (recent_story_time + timedelta(minutes=30)).isoformat()
    newsletter_date = recent_story_time.date().isoformat()
    display_timestamp = recent_story_time.astimezone().strftime("%b %-d, %-I:%M %p %Z")

    run_id = create_completed_ingestion_run(repository, "additional_source")
    story_id = repository.upsert_story(
        {
            "source_type": "additional_source",
            "source_name": "Macro Wire",
            "subject": "[markets] Rates reset",
            "url": "https://example.com/markets/rates-reset",
            "anchor_text": "Rates reset changes software valuations",
            "context": "Repository context for rates reset",
            "category": "Markets / stocks / macro / economy",
            "published_at": recent_story_time_iso,
            "summary": "Rates reset summary",
        },
        ingestion_run_id=run_id,
    )
    repository.upsert_article_snapshot(
        story_id,
        "Rates reset changes software valuations and reprices growth names.",
        summary_headline="Rates reset changes software valuations",
        summary_body=(
            "Key takeaways\n"
            "- Rates reset changes software valuations.\n\n"
            "Why this matters to me\n"
            "This matters for software multiples."
        ),
        summary_model="gpt-5-mini",
        summarized_at=recent_summary_time_iso,
    )
    repository.upsert_daily_newsletter(
        newsletter_date=newsletter_date,
        subject="AI Signal Daily",
        body=(
            "Story: Rates reset changes software valuations\n\n"
            "URL: https://example.com/markets/rates-reset\n\n"
            "Key takeaways\n"
            "- Rates reset changes software valuations.\n\n"
            "Why this matters to me\n"
            "This matters for software multiples."
        ),
        html_body=(
            "<html><body><h1>AI Signal Daily</h1>"
            "<p>Rates reset changes software valuations</p>"
            "</body></html>"
        ),
        selected_items=[
            {
                "title": "Rates reset changes software valuations",
                "url": "https://example.com/markets/rates-reset",
            }
        ],
        metadata={"ranked_candidates": 7, "selected": 1},
        content={
            "version": 1,
            "render_groups": {
                "Markets / stocks / macro / economy": [
                    {
                        "title": "Rates reset changes software valuations",
                        "url": "https://example.com/markets/rates-reset",
                        "body": (
                            "Key takeaways\n"
                            "- Rates reset changes software valuations.\n\n"
                            "Why this matters to me\n"
                            "This matters for software multiples."
                        ),
                        "source_name": "Macro Wire",
                        "published_at": recent_story_time_iso,
                        "display_timestamp": display_timestamp,
                        "timestamp_iso": recent_story_time_iso,
                    }
                ]
            },
            "ranked_candidates": 7,
            "selected": 1,
            "accepted_items": 1,
        },
    )

    return {
        "config_path": config_path,
        "database_path": root / "curator.sqlite3",
        "newsletter_date": newsletter_date,
    }


def start_admin_server(
    *,
    config_path: Path,
    host: str,
    port: int,
    admin_token: str,
    public_base_url: str,
    stdout_handle,
) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update(
        {
            "NEWSLETTER_CONFIG": str(config_path),
            "CURATOR_ADMIN_TOKEN": admin_token,
            "CURATOR_ADMIN_ENABLE_PREVIEW": "1",
            "CURATOR_EXPOSE_LOGIN_LINKS": "1",
            "CURATOR_APP_HOST": host,
            "CURATOR_APP_PORT": str(port),
            "CURATOR_PUBLIC_BASE_URL": public_base_url,
        }
    )
    return subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "admin_app.py")],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=stdout_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )


def stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def wait_for_server(base_url: str, *, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    health_url = f"{base_url}/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {health_url} to become healthy.")


def run_playwright_command(
    *command: str,
    output_dir: Path,
    session: str,
    pwcli_path: Path,
) -> str:
    completed = subprocess.run(
        ["bash", str(pwcli_path), "--session", session, *command],
        cwd=str(output_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Playwright command failed: {' '.join(command)}\n{details}")
    return completed.stdout


def extract_cli_artifact_path(output: str, *, suffix: str) -> Path:
    pattern = re.compile(rf"\(([^)]+{re.escape(suffix)})\)")
    match = pattern.search(output)
    if match is None:
        raise RuntimeError(f"Failed to locate a {suffix} artifact in Playwright output:\n{output}")
    return Path(match.group(1))


def read_snapshot(
    *,
    output_dir: Path,
    session: str,
    pwcli_path: Path,
) -> str:
    output = run_playwright_command("snapshot", output_dir=output_dir, session=session, pwcli_path=pwcli_path)
    snapshot_path = output_dir / extract_cli_artifact_path(output, suffix=".yml")
    return snapshot_path.read_text(encoding="utf-8")


def write_named_screenshot(
    name: str,
    *,
    output_dir: Path,
    session: str,
    pwcli_path: Path,
    ref: str | None = None,
) -> Path:
    command = ["screenshot"]
    if ref:
        command.append(ref)
    output = run_playwright_command(*command, output_dir=output_dir, session=session, pwcli_path=pwcli_path)
    artifact_path = output_dir / extract_cli_artifact_path(output, suffix=".png")
    target_path = output_dir / name
    shutil.copy2(artifact_path, target_path)
    return target_path


def extract_ref(snapshot_text: str, *, role: str, accessible_name: str) -> str:
    pattern = re.compile(rf'{re.escape(role)} "{re.escape(accessible_name)}".*?\[ref=(e\d+)\]')
    match = pattern.search(snapshot_text)
    if match is None:
        raise RuntimeError(
            f"Failed to find ref for role={role!r} accessible_name={accessible_name!r} in snapshot."
        )
    return match.group(1)


def extract_ref_with_fallback(snapshot_text: str, *, roles: list[str], accessible_name: str) -> str:
    for role in roles:
        try:
            return extract_ref(snapshot_text, role=role, accessible_name=accessible_name)
        except RuntimeError:
            continue
    raise RuntimeError(
        f"Failed to find ref for roles={roles!r} accessible_name={accessible_name!r} in snapshot."
    )


def extract_confirm_url(snapshot_text: str) -> str:
    match = re.search(r"https?://[^\s]+/login/confirm\?token=[A-Za-z0-9\-_]+", snapshot_text)
    if match is None:
        raise RuntimeError("Failed to find the subscriber login confirmation URL in the snapshot.")
    return match.group(0)


def extract_confirm_path(confirm_url: str) -> str:
    parsed = urlparse(confirm_url)
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.path}{query}"


def load_saved_profile(database_path: Path, subscriber_email: str) -> dict:
    repository = SQLiteRepository(database_path)
    repository.initialize()
    subscriber = repository.get_subscriber_by_email(subscriber_email)
    if subscriber is None:
        raise RuntimeError(f"Seeded subscriber {subscriber_email!r} was not found in the database.")
    return repository.get_subscriber_profile(int(subscriber["id"]))


def ensure_contains(text: str, needle: str, *, context: str) -> None:
    if needle not in text:
        raise RuntimeError(f"Expected to find {needle!r} in {context}.")


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pwcli_path = resolve_pwcli_path()
    if not pwcli_path.exists():
        raise RuntimeError(
            f"Playwright CLI wrapper not found at {pwcli_path}. "
            "Install the Codex playwright skill first."
        )
    if shutil.which("npx") is None:
        raise RuntimeError("npx is required to run the playwright CLI harness.")

    server_log_path = output_dir / "server.log"
    manifest_path = output_dir / "manifest.json"
    browser_session = "admin-ui-e2e"
    base_url = f"http://{args.host}:{args.port}"
    public_base_url = str(args.public_base_url or base_url).strip().rstrip("/")
    screenshots: dict[str, str] = {}

    with fixture_root_context(args.fixture_dir) as fixture_root:
        seed = seed_review_fixture(
            fixture_root,
            host=args.host,
            port=args.port,
            public_base_url=public_base_url,
            subscriber_email=args.subscriber_email,
        )
        server_log_handle = server_log_path.open("w", encoding="utf-8")
        server_process: subprocess.Popen[str] | None = None
        try:
            server_process = start_admin_server(
                config_path=seed["config_path"],
                host=args.host,
                port=args.port,
                admin_token=args.admin_token,
                public_base_url=public_base_url,
                stdout_handle=server_log_handle,
            )
            wait_for_server(base_url)

            run_playwright_command(
                "open",
                f"{base_url}/login",
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            run_playwright_command(
                "resize",
                "1440",
                "1400",
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            screenshots["login_page"] = str(
                write_named_screenshot(
                    "01-login-page.png",
                    output_dir=output_dir,
                    session=browser_session,
                    pwcli_path=pwcli_path,
                )
            )

            login_snapshot = read_snapshot(
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            ensure_contains(login_snapshot, "Sign in to Newsletter Curator", context="login snapshot")
            email_ref = extract_ref(login_snapshot, role="textbox", accessible_name="Email address")
            send_link_ref = extract_ref(login_snapshot, role="button", accessible_name="Send sign-in link")
            run_playwright_command(
                "fill",
                email_ref,
                args.subscriber_email,
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            run_playwright_command(
                "click",
                send_link_ref,
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            login_link_snapshot = read_snapshot(
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            ensure_contains(login_link_snapshot, "Temporary sign-in link", context="login link snapshot")
            confirm_url = extract_confirm_url(login_link_snapshot)
            if not confirm_url.startswith(f"{public_base_url}/login/confirm?token="):
                raise RuntimeError(
                    "Subscriber login link did not use the configured public base URL. "
                    f"expected_prefix={public_base_url}/login/confirm?token= actual={confirm_url}"
                )
            screenshots["login_link"] = str(
                write_named_screenshot(
                    "02-login-link-exposed.png",
                    output_dir=output_dir,
                    session=browser_session,
                    pwcli_path=pwcli_path,
                )
            )
            confirm_path = extract_confirm_path(confirm_url)

            run_playwright_command(
                "goto",
                f"{base_url}{confirm_path}",
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            account_snapshot = read_snapshot(
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            ensure_contains(account_snapshot, "Your subscriber account", context="account snapshot")
            ensure_contains(account_snapshot, args.subscriber_email, context="account snapshot")
            screenshots["account_page"] = str(
                write_named_screenshot(
                    "03-account-page.png",
                    output_dir=output_dir,
                    session=browser_session,
                    pwcli_path=pwcli_path,
                )
            )

            edit_settings_ref = extract_ref(account_snapshot, role="link", accessible_name="Settings")
            run_playwright_command(
                "click",
                edit_settings_ref,
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            settings_snapshot = read_snapshot(
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            ensure_contains(settings_snapshot, "AI Wire", context="settings snapshot")
            ensure_contains(settings_snapshot, "Unavailable", context="settings snapshot")
            screenshots["settings_page"] = str(
                write_named_screenshot(
                    "04-settings-page.png",
                    output_dir=output_dir,
                    session=browser_session,
                    pwcli_path=pwcli_path,
                )
            )

            persona_ref = extract_ref(settings_snapshot, role="textbox", accessible_name="Persona text")
            source_search_ref = extract_ref_with_fallback(
                settings_snapshot,
                roles=["searchbox", "textbox"],
                accessible_name="Search preferred sources",
            )
            run_playwright_command(
                "fill",
                source_search_ref,
                "Signal",
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            filtered_settings_snapshot = read_snapshot(
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            ensure_contains(filtered_settings_snapshot, "Signal Mail", context="filtered settings snapshot")
            if "Chip Insider" in filtered_settings_snapshot:
                raise RuntimeError("Preferred-source search did not filter the all-sources list as expected.")
            signal_mail_ref = extract_ref(
                filtered_settings_snapshot,
                role="checkbox",
                accessible_name="Signal Mail Gmail newsletter Available",
            )
            save_settings_ref = extract_ref(filtered_settings_snapshot, role="button", accessible_name="Save settings")
            run_playwright_command(
                "fill",
                persona_ref,
                args.updated_persona,
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            run_playwright_command(
                "check",
                signal_mail_ref,
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            run_playwright_command(
                "click",
                save_settings_ref,
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            settings_saved_snapshot = read_snapshot(
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            ensure_contains(settings_saved_snapshot, "Subscriber settings saved.", context="saved settings snapshot")
            ensure_contains(settings_saved_snapshot, args.updated_persona, context="saved settings snapshot")
            screenshots["settings_saved"] = str(
                write_named_screenshot(
                    "05-settings-saved.png",
                    output_dir=output_dir,
                    session=browser_session,
                    pwcli_path=pwcli_path,
                )
            )

            saved_profile = load_saved_profile(seed["database_path"], args.subscriber_email)
            if saved_profile["persona_text"] != args.updated_persona:
                raise RuntimeError("Saved persona text did not persist to SQLite as expected.")
            preferred_sources = set(saved_profile.get("preferred_sources", []))
            if preferred_sources != {"Macro Wire", "Signal Mail", "AI Wire"}:
                raise RuntimeError(
                    "Saved preferred sources did not preserve disabled selections as expected."
                )

            run_playwright_command(
                "goto",
                f"{base_url}/admin/login",
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            admin_login_snapshot = read_snapshot(
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            ensure_contains(admin_login_snapshot, "Sign in to the control room", context="admin login snapshot")
            admin_token_ref = extract_ref(admin_login_snapshot, role="textbox", accessible_name="Admin token")
            admin_sign_in_ref = extract_ref(admin_login_snapshot, role="button", accessible_name="Sign in")
            run_playwright_command(
                "fill",
                admin_token_ref,
                args.admin_token,
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            run_playwright_command(
                "click",
                admin_sign_in_ref,
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            admin_snapshot = read_snapshot(
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            ensure_contains(admin_snapshot, "Control Room", context="admin config snapshot")
            screenshots["admin_control_room"] = str(
                write_named_screenshot(
                    "06-admin-control-room.png",
                    output_dir=output_dir,
                    session=browser_session,
                    pwcli_path=pwcli_path,
                )
            )

            review_digest_ref = extract_ref(admin_snapshot, role="link", accessible_name="Review Today's Digest")
            run_playwright_command(
                "click",
                review_digest_ref,
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            preview_snapshot = read_snapshot(
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            ensure_contains(preview_snapshot, "AI Signal Daily", context="preview snapshot")
            ensure_contains(
                preview_snapshot,
                "Rates reset changes software valuations",
                context="preview snapshot",
            )
            screenshots["admin_preview"] = str(
                write_named_screenshot(
                    "07-admin-preview.png",
                    output_dir=output_dir,
                    session=browser_session,
                    pwcli_path=pwcli_path,
                )
            )

            run_playwright_command(
                "mousewheel",
                "0",
                "1400",
                output_dir=output_dir,
                session=browser_session,
                pwcli_path=pwcli_path,
            )
            screenshots["preview_detail"] = str(
                write_named_screenshot(
                    "08-preview-detail.png",
                    output_dir=output_dir,
                    session=browser_session,
                    pwcli_path=pwcli_path,
                )
            )

            manifest = {
                "status": "completed",
                "base_url": base_url,
                "public_base_url": public_base_url,
                "admin_token": args.admin_token,
                "subscriber_email": args.subscriber_email,
                "updated_persona": args.updated_persona,
                "config_path": str(seed["config_path"]),
                "database_path": str(seed["database_path"]),
                "server_log_path": str(server_log_path),
                "screenshots": screenshots,
                "saved_profile": {
                    "persona_text": saved_profile["persona_text"],
                    "preferred_sources": list(saved_profile["preferred_sources"]),
                },
            }
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0
        finally:
            try:
                run_playwright_command(
                    "close",
                    output_dir=output_dir,
                    session=browser_session,
                    pwcli_path=pwcli_path,
                )
            except Exception:
                pass
            stop_process(server_process)
            server_log_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
