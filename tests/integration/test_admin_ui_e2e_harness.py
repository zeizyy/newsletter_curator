from __future__ import annotations

import argparse
import json
from pathlib import Path

from curator.repository import SQLiteRepository
from scripts import run_admin_ui_e2e_harness as harness


class _FakeProcess:
    def __init__(self) -> None:
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self) -> None:
        self._returncode = 0

    def wait(self, timeout=None) -> int:
        self._returncode = 0
        return 0

    def kill(self) -> None:
        self._returncode = 0


def test_admin_ui_e2e_harness_emits_manifest_and_updates_profile(tmp_path, monkeypatch, capsys):
    output_dir = tmp_path / "artifacts"
    fixture_dir = tmp_path / "fixture"
    fake_pwcli = tmp_path / "fake_pwcli.sh"
    fake_pwcli.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    monkeypatch.setattr(
        harness,
        "parse_args",
        lambda: argparse.Namespace(
            output_dir=output_dir,
            fixture_dir=fixture_dir,
            host="127.0.0.1",
            port=8091,
            admin_token="local-review-token",
            subscriber_email="existing@example.com",
            updated_persona="Focus on chips, software margins, and rates.",
            public_base_url="http://127.0.0.1:8091",
        ),
    )
    monkeypatch.setattr(harness, "resolve_pwcli_path", lambda: fake_pwcli)
    monkeypatch.setattr(harness.shutil, "which", lambda name: "/usr/bin/npx" if name == "npx" else None)
    monkeypatch.setattr(harness, "start_admin_server", lambda **kwargs: _FakeProcess())
    monkeypatch.setattr(harness, "wait_for_server", lambda *args, **kwargs: None)

    cli_dir = output_dir / ".playwright-cli"
    state = {
        "page": "login",
        "email": "",
        "persona": "Focus on semis, software margins, and bond yields.",
        "source_search": "",
        "signal_checked": False,
        "shot_index": 0,
        "snapshot_index": 0,
        "confirm_url": "http://127.0.0.1:8091/login/confirm?token=fake-token",
        "db_path": fixture_dir / "curator.sqlite3",
    }

    def snapshot_text() -> str:
        page = state["page"]
        if page == "login":
            return "\n".join(
                [
                    '- heading "Sign in to Newsletter Curator" [level=1] [ref=e7]',
                    '- textbox "Email address" [ref=e26]',
                    '- button "Send sign-in link" [ref=e28] [cursor=pointer]',
                ]
            )
        if page == "login_link":
            return "\n".join(
                [
                    '- generic [ref=e20]: Sign-in link sent to existing@example.com.',
                    '- heading "Temporary sign-in link" [level=2] [ref=e35]',
                    f"- generic [ref=e38]: {state['confirm_url']}",
                ]
            )
        if page == "account":
            return "\n".join(
                [
                    '- heading "Your subscriber account" [level=1] [ref=e7]',
                    '- heading "existing@example.com" [level=2] [ref=e25]',
                    '- link "Settings" [ref=e17] [cursor=pointer]:',
                ]
            )
        if page == "settings":
            lines = [
                '- heading "Your digest settings" [level=1] [ref=e7]',
                '- textbox "Persona text" [ref=e29]: Focus on semis, software margins, and bond yields.',
                f'- searchbox "Search preferred sources" [ref=e31]: {state["source_search"]}',
                '- heading "Suggested sources" [level=3] [ref=e50]',
                '- checkbox "Signal Mail Available" [ref=e61]',
                '- heading "Your selected sources (2)" [level=3] [ref=e34]',
                '- strong [ref=e42]: AI Wire',
                '- generic [ref=e43]: Unavailable',
            ]
            if state["source_search"].lower() == "signal":
                lines[3] = '- heading "Matching sources" [level=3] [ref=e50]'
            lines.append('- button "Save settings" [ref=e64] [cursor=pointer]')
            return "\n".join(lines)
        if page == "settings_saved":
            return "\n".join(
                [
                    '- generic [ref=e20]: Subscriber settings saved.',
                    '- textbox "Persona text" [ref=e30]: Focus on chips, software margins, and rates.',
                    '- checkbox "Signal Mail Available" [checked] [ref=e62]',
                ]
            )
        if page == "admin":
            return "\n".join(
                [
                    '- heading "Control Room" [level=1] [ref=e7]',
                    '- link "Review Today\'s Digest" [ref=e21] [cursor=pointer]:',
                ]
            )
        if page == "admin_login":
            return "\n".join(
                [
                    '- heading "Sign in to the control room" [level=1] [ref=e7]',
                    '- textbox "Admin token" [ref=e26]',
                    '- button "Sign in" [ref=e28] [cursor=pointer]',
                ]
            )
        if page == "preview":
            return "\n".join(
                [
                    '- heading "AI Signal Daily" [level=2] [ref=e29]',
                    "- generic [ref=e54]: Story: Rates reset changes software valuations URL: https://example.com/markets/rates-reset Key takeaways - Rates reset changes software valuations. Why this matters to me This matters for software multiples.",
                ]
            )
        raise AssertionError(f"Unexpected fake page state: {page}")

    def fake_run_playwright_command(*command: str, output_dir: Path, session: str, pwcli_path: Path) -> str:
        del session, pwcli_path
        cli_dir.mkdir(parents=True, exist_ok=True)
        action = command[0]
        if action == "open":
            state["page"] = "login"
            return "### Page\n- Page Title: Subscriber Login | Newsletter Curator\n"
        if action == "resize":
            return "### Ran Playwright code\n"
        if action == "snapshot":
            state["snapshot_index"] += 1
            path = cli_dir / f"page-{state['snapshot_index']:02d}.yml"
            path.write_text(snapshot_text(), encoding="utf-8")
            return f"### Snapshot\n- [Snapshot](.playwright-cli/{path.name})\n"
        if action == "fill":
            ref, value = command[1], command[2]
            if ref == "e26":
                if state["page"] == "admin_login":
                    state["admin_token"] = value
                else:
                    state["email"] = value
            elif ref == "e29":
                state["persona"] = value
            elif ref == "e31":
                state["source_search"] = value
            return "### Ran Playwright code\n"
        if action == "click":
            ref = command[1]
            if ref == "e28":
                if state["page"] == "admin_login":
                    state["page"] = "admin"
                else:
                    state["page"] = "login_link"
            elif ref == "e17":
                state["page"] = "settings"
                state["source_search"] = ""
            elif ref == "e64":
                state["page"] = "settings_saved"
                repository = SQLiteRepository(state["db_path"])
                repository.initialize()
                subscriber = repository.get_subscriber_by_email("existing@example.com")
                repository.upsert_subscriber_profile(
                    int(subscriber["id"]),
                    persona_text=state["persona"],
                    preferred_sources=["Macro Wire", "Signal Mail", "AI Wire"],
                )
            elif ref == "e21":
                state["page"] = "preview"
            return "### Ran Playwright code\n"
        if action == "check":
            state["signal_checked"] = True
            return "### Ran Playwright code\n"
        if action == "goto":
            url = command[1]
            if "/login/confirm" in url:
                state["page"] = "account"
            elif url.endswith("/admin/login"):
                state["page"] = "admin_login"
            return "### Page\n"
        if action == "mousewheel":
            return "### Ran Playwright code\n"
        if action == "screenshot":
            state["shot_index"] += 1
            prefix = "element" if len(command) > 1 else "page"
            path = cli_dir / f"{prefix}-{state['shot_index']:02d}.png"
            path.write_bytes(b"fake-png")
            label = "Screenshot of element" if len(command) > 1 else "Screenshot of viewport"
            return f"### Result\n- [{label}](.playwright-cli/{path.name})\n"
        if action == "close":
            return "Browser 'admin-ui-e2e' closed\n"
        raise AssertionError(f"Unexpected fake command: {command}")

    monkeypatch.setattr(harness, "run_playwright_command", fake_run_playwright_command)

    result = harness.main()

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["public_base_url"] == "http://127.0.0.1:8091"
    assert payload["saved_profile"]["persona_text"] == "Focus on chips, software margins, and rates."
    assert payload["saved_profile"]["preferred_sources"] == ["Macro Wire", "Signal Mail", "AI Wire"]

    screenshot_names = {
        "01-login-page.png",
        "02-login-link-exposed.png",
        "03-account-page.png",
        "04-settings-page.png",
        "05-settings-saved.png",
        "06-admin-control-room.png",
        "07-admin-preview.png",
        "08-preview-detail.png",
    }
    assert {path.name for path in output_dir.glob("*.png")} == screenshot_names

    manifest_path = output_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["screenshots"]["preview_detail"].endswith("08-preview-detail.png")
