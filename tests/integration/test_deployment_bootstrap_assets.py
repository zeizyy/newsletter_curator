from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

from scripts import bootstrap_server


def test_deployment_bootstrap_assets(tmp_path, repo_root):
    output_dir = tmp_path / "deploy-generated"
    script_path = repo_root / "scripts" / "bootstrap_server.py"
    repo_dir = repo_root
    config_path = repo_root / "config.yaml"

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--repo-dir",
            str(repo_dir),
            "--output-dir",
            str(output_dir),
            "--uv-bin",
            "/usr/local/bin/uv",
            "--config-path",
            str(config_path),
            "--admin-host",
            "0.0.0.0",
            "--admin-port",
            "9090",
            "--admin-token",
            "test-admin-token",
            "--openai-api-key",
            "test-openai-key",
            "--buttondown-api-key",
            "test-buttondown-key",
            "--public-base-url",
            "https://curator.example.com",
            "--enable-telemetry",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    env_file = output_dir / "newsletter-curator.env"
    admin_script = output_dir / "start_admin_server.sh"
    daily_script = output_dir / "run_daily_pipeline.sh"
    fetch_gmail_script = output_dir / "run_fetch_gmail.sh"
    fetch_sources_script = output_dir / "run_fetch_sources.sh"
    deliver_script = output_dir / "run_deliver_digest.sh"
    cron_file = output_dir / "newsletter-curator.cron"
    service_file = output_dir / "newsletter-curator-admin.service"

    for path in [
        env_file,
        admin_script,
        daily_script,
        fetch_gmail_script,
        fetch_sources_script,
        deliver_script,
        cron_file,
        service_file,
    ]:
        assert path.exists()

    env_text = env_file.read_text(encoding="utf-8")
    assert "CURATOR_ADMIN_HOST=0.0.0.0" in env_text
    assert "CURATOR_ADMIN_PORT=9090" in env_text
    assert "CURATOR_ADMIN_TOKEN=test-admin-token" in env_text
    assert "OPENAI_API_KEY=test-openai-key" in env_text
    assert "BUTTONDOWN_API_KEY=test-buttondown-key" in env_text
    assert "CURATOR_PUBLIC_BASE_URL=https://curator.example.com" in env_text
    assert "CURATOR_ENABLE_TELEMETRY=1" in env_text
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"

    admin_script_text = admin_script.read_text(encoding="utf-8")
    assert "admin_app.py" in admin_script_text
    assert str(env_file) in admin_script_text
    assert "\"$@\"" in admin_script_text
    assert oct(admin_script.stat().st_mode & 0o777) == "0o700"

    deliver_script_text = deliver_script.read_text(encoding="utf-8")
    assert "deliver_digest.py" in deliver_script_text
    assert "\"$@\"" in deliver_script_text

    cron_text = cron_file.read_text(encoding="utf-8")
    assert "CRON_TZ=" not in cron_text
    assert "30 14 * * *" in cron_text
    assert str(daily_script) in cron_text
    assert str(fetch_gmail_script) not in cron_text
    assert str(fetch_sources_script) not in cron_text
    assert str(deliver_script) not in cron_text

    service_text = service_file.read_text(encoding="utf-8")
    assert f"WorkingDirectory={repo_dir}" in service_text
    assert f"EnvironmentFile={env_file}" in service_text
    assert f"ExecStart={admin_script}" in service_text

    assert "Generated deployment assets:" in result.stdout


def test_install_systemd_user_service_is_rerunnable(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))

    calls: list[list[str]] = []

    def fake_run(cmd, check):
        calls.append(list(cmd))

    monkeypatch.setattr(bootstrap_server.subprocess, "run", fake_run)

    service_file = tmp_path / "newsletter-curator-admin.service"
    service_file.write_text("[Unit]\nDescription=test\n", encoding="utf-8")

    bootstrap_server.install_systemd_user_service(service_file, "newsletter-curator-admin")

    installed_file = fake_home / ".config" / "systemd" / "user" / "newsletter-curator-admin.service"
    assert installed_file.exists()
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "newsletter-curator-admin"],
        ["systemctl", "--user", "restart", "newsletter-curator-admin"],
    ]


def test_enable_user_linger_runs_loginctl(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, check):
        calls.append(list(cmd))

    monkeypatch.setattr(bootstrap_server.subprocess, "run", fake_run)
    bootstrap_server.enable_user_linger("deploy-user")
    assert calls == [["loginctl", "enable-linger", "deploy-user"]]
