from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

from scripts import bootstrap_server


def _run_bootstrap(
    tmp_path,
    repo_root,
    *,
    extra_env: dict[str, str] | None = None,
    uv_bin: str = "/usr/local/bin/uv",
):
    output_dir = tmp_path / "deploy-generated"
    script_path = repo_root / "scripts" / "bootstrap_server.py"
    repo_dir = repo_root
    config_path = repo_root / "config.yaml"
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--repo-dir",
            str(repo_dir),
            "--output-dir",
            str(output_dir),
            "--uv-bin",
            uv_bin,
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
        env=env,
    )

    return result, {
        "output_dir": output_dir,
        "env_file": output_dir / "newsletter-curator.env",
        "admin_script": output_dir / "start_admin_server.sh",
        "daily_script": output_dir / "run_daily_pipeline.sh",
        "fetch_gmail_script": output_dir / "run_fetch_gmail.sh",
        "fetch_sources_script": output_dir / "run_fetch_sources.sh",
        "deliver_script": output_dir / "run_deliver_digest.sh",
        "cron_file": output_dir / "newsletter-curator.cron",
        "service_file": output_dir / "newsletter-curator-admin.service",
    }


def _write_fake_command(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_fake_runtime(fake_bin: Path, log_path: Path) -> None:
    _write_fake_command(
        fake_bin / "systemctl",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import os",
                "import sys",
                f"log_path = {str(log_path)!r}",
                "with open(log_path, 'a', encoding='utf-8') as handle:",
                "    handle.write('systemctl ' + ' '.join(sys.argv[1:]) + '\\n')",
                "action = sys.argv[2] if len(sys.argv) > 2 else ''",
                "if action == 'stop' and os.getenv('FAKE_SYSTEMCTL_FAIL_STOP') == '1':",
                "    sys.exit(1)",
                "if action == 'start' and os.getenv('FAKE_SYSTEMCTL_FAIL_START') == '1':",
                "    sys.exit(1)",
                "sys.exit(0)",
                "",
            ]
        ),
    )
    _write_fake_command(
        fake_bin / "uv",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import os",
                "import sys",
                f"log_path = {str(log_path)!r}",
                "with open(log_path, 'a', encoding='utf-8') as handle:",
                "    handle.write('uv ' + ' '.join(sys.argv[1:]) + '\\n')",
                "sys.exit(int(os.getenv('FAKE_UV_EXIT_CODE', '0')))",
                "",
            ]
        ),
    )


def test_deployment_bootstrap_assets(tmp_path, repo_root):
    result, paths = _run_bootstrap(tmp_path, repo_root)
    output_dir = paths["output_dir"]
    env_file = paths["env_file"]
    admin_script = paths["admin_script"]
    daily_script = paths["daily_script"]
    fetch_gmail_script = paths["fetch_gmail_script"]
    fetch_sources_script = paths["fetch_sources_script"]
    deliver_script = paths["deliver_script"]
    cron_file = paths["cron_file"]
    service_file = paths["service_file"]
    repo_dir = repo_root

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
    assert "CURATOR_MCP_TOKEN=test-admin-token" in env_text
    assert "CURATOR_ADMIN_SERVICE_NAME=newsletter-curator-admin" in env_text
    assert "CURATOR_PAUSE_ADMIN_DURING_DAILY=1" in env_text
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

    daily_script_text = daily_script.read_text(encoding="utf-8")
    assert 'systemctl --user stop "$CURATOR_ADMIN_SERVICE_NAME"' in daily_script_text
    assert 'systemctl --user start "$CURATOR_ADMIN_SERVICE_NAME"' in daily_script_text
    assert "trap resume_admin_service EXIT" in daily_script_text
    assert "trap handle_interrupt INT" in daily_script_text
    assert "trap handle_terminate TERM" in daily_script_text

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
    assert "Warning: --public-base-url has no explicit port while --admin-port is set to 9090." in result.stdout


def test_generated_daily_wrapper_stops_and_restarts_admin_service(tmp_path, repo_root):
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    command_log = tmp_path / "commands.log"
    _write_fake_runtime(fake_bin, command_log)
    _, paths = _run_bootstrap(
        tmp_path,
        repo_root,
        extra_env={"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
        uv_bin="uv",
    )

    result = subprocess.run(
        [str(paths["daily_script"]), "--dry-run-recipient", "you@example.com"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "FAKE_UV_EXIT_CODE": "0",
        },
    )

    assert result.returncode == 0
    assert command_log.read_text(encoding="utf-8").splitlines() == [
        "systemctl --user stop newsletter-curator-admin",
        "uv run python daily_pipeline.py --dry-run-recipient you@example.com",
        "systemctl --user start newsletter-curator-admin",
    ]


def test_generated_daily_wrapper_restarts_admin_service_after_pipeline_failure(tmp_path, repo_root):
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    command_log = tmp_path / "commands.log"
    _write_fake_runtime(fake_bin, command_log)
    _, paths = _run_bootstrap(
        tmp_path,
        repo_root,
        extra_env={"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
        uv_bin="uv",
    )

    result = subprocess.run(
        [str(paths["daily_script"])],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "FAKE_UV_EXIT_CODE": "7",
        },
    )

    assert result.returncode == 7
    assert command_log.read_text(encoding="utf-8").splitlines() == [
        "systemctl --user stop newsletter-curator-admin",
        "uv run python daily_pipeline.py",
        "systemctl --user start newsletter-curator-admin",
    ]


def test_generated_daily_wrapper_continues_when_admin_stop_fails(tmp_path, repo_root):
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    command_log = tmp_path / "commands.log"
    _write_fake_runtime(fake_bin, command_log)
    _, paths = _run_bootstrap(
        tmp_path,
        repo_root,
        extra_env={"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
        uv_bin="uv",
    )

    result = subprocess.run(
        [str(paths["daily_script"])],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "FAKE_SYSTEMCTL_FAIL_STOP": "1",
            "FAKE_UV_EXIT_CODE": "0",
        },
    )

    assert result.returncode == 0
    assert "continuing daily pipeline" in result.stderr
    assert command_log.read_text(encoding="utf-8").splitlines() == [
        "systemctl --user stop newsletter-curator-admin",
        "uv run python daily_pipeline.py",
        "systemctl --user start newsletter-curator-admin",
    ]


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
