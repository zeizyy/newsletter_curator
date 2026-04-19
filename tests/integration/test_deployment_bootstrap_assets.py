from __future__ import annotations

import argparse
import json
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
    include_api_keys: bool = True,
    app_host: str = "0.0.0.0",
    app_port: int = 9090,
    public_base_url: str = "https://curator.example.com",
):
    output_dir = tmp_path / "deploy-generated"
    script_path = repo_root / "scripts" / "bootstrap_server.py"
    repo_dir = repo_root
    config_path = repo_root / "config.yaml"
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    command = [
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
        "--app-host",
        app_host,
        "--app-port",
        str(app_port),
        "--admin-token",
        "test-admin-token",
        "--debug-log-token",
        "test-debug-log-token",
        "--public-base-url",
        public_base_url,
    ]
    if include_api_keys:
        command.extend(
            [
                "--openai-api-key",
                "test-openai-key",
                "--buttondown-api-key",
                "test-buttondown-key",
            ]
        )

    result = subprocess.run(
        command,
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
        "logrotate_file": output_dir / "newsletter-curator.logrotate",
        "cron_file": output_dir / "newsletter-curator.cron",
        "service_file": output_dir / "newsletter-curator-admin.service",
        "caddy_file": output_dir / "newsletter-curator.Caddyfile",
    }


def _write_fake_command(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_fake_runtime(fake_bin: Path, log_path: Path) -> None:
    _write_fake_command(
        fake_bin / "date",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import os",
                "import sys",
                "if sys.argv[1:] == ['+%u']:",
                "    print(os.getenv('FAKE_DATE_WEEKDAY', '2'))",
                "    sys.exit(0)",
                "print('Tue Apr 21 00:00:00 UTC 2026')",
                "sys.exit(0)",
                "",
            ]
        ),
    )
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
                "if action == 'is-active':",
                "    sys.exit(0 if os.getenv('FAKE_SYSTEMCTL_ACTIVE') == '1' else 3)",
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


def _write_fake_runtime_with_alert_capture(
    fake_bin: Path,
    log_path: Path,
    alert_capture_path: Path,
) -> None:
    _write_fake_runtime(fake_bin, log_path)
    _write_fake_command(
        fake_bin / "uv",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import os",
                "from pathlib import Path",
                "import sys",
                f"log_path = {str(log_path)!r}",
                f"alert_capture_path = {str(alert_capture_path)!r}",
                "args = sys.argv[1:]",
                "with open(log_path, 'a', encoding='utf-8') as handle:",
                "    handle.write('uv ' + ' '.join(args) + '\\n')",
                "if args[:3] == ['run', 'python', 'daily_pipeline.py']:",
                "    print('pipeline stdout before failure')",
                "    print('pipeline stderr before failure', file=sys.stderr)",
                "    sys.exit(int(os.getenv('FAKE_UV_EXIT_CODE', '0')))",
                "if args[:3] == ['run', 'python', 'scripts/send_pipeline_failure_alert.py']:",
                "    output_file = args[args.index('--output-file') + 1]",
                "    payload = {",
                "        'source': args[args.index('--source') + 1],",
                "        'exit_status': args[args.index('--exit-status') + 1],",
                "        'output_file': output_file,",
                "        'output': Path(output_file).read_text(encoding='utf-8'),",
                "    }",
                "    Path(alert_capture_path).write_text(json.dumps(payload), encoding='utf-8')",
                "    sys.exit(int(os.getenv('FAKE_ALERT_EXIT_CODE', '0')))",
                "sys.exit(0)",
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
    logrotate_file = paths["logrotate_file"]
    cron_file = paths["cron_file"]
    service_file = paths["service_file"]
    caddy_file = paths["caddy_file"]
    repo_dir = repo_root

    for path in [
        env_file,
        admin_script,
        daily_script,
        fetch_gmail_script,
        fetch_sources_script,
        deliver_script,
        logrotate_file,
        cron_file,
        service_file,
        caddy_file,
    ]:
        assert path.exists()

    env_text = env_file.read_text(encoding="utf-8")
    assert "CURATOR_APP_HOST=127.0.0.1" in env_text
    assert "CURATOR_APP_PORT=9090" in env_text
    assert "CURATOR_ADMIN_TOKEN=test-admin-token" in env_text
    assert "CURATOR_MCP_TOKEN=test-admin-token" in env_text
    assert "CURATOR_DEBUG_LOG_TOKEN=test-debug-log-token" in env_text
    assert f"CURATOR_DEBUG_LOG_PATH={output_dir / 'debug.ndjson'}" in env_text
    assert "CURATOR_ADMIN_SERVICE_NAME=newsletter-curator-admin" in env_text
    assert "CURATOR_PAUSE_ADMIN_DURING_DAILY=1" in env_text
    assert "CURATOR_TRUST_PROXY_HEADERS=1" in env_text
    assert "CURATOR_GUNICORN_WORKERS=1" in env_text
    assert "CURATOR_GUNICORN_WORKER_CLASS=gthread" in env_text
    assert "CURATOR_GUNICORN_THREADS=4" in env_text
    assert "CURATOR_GUNICORN_TIMEOUT=120" in env_text
    assert "CURATOR_GUNICORN_GRACEFUL_TIMEOUT=30" in env_text
    assert "OPENAI_API_KEY=test-openai-key" in env_text
    assert "BUTTONDOWN_API_KEY=test-buttondown-key" in env_text
    assert "CURATOR_PUBLIC_BASE_URL=https://curator.example.com" in env_text
    assert f"XDG_RUNTIME_DIR=/run/user/{os.getuid()}" in env_text
    assert f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{os.getuid()}/bus" in env_text
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"

    admin_script_text = admin_script.read_text(encoding="utf-8")
    assert "gunicorn" in admin_script_text
    assert 'admin_app:app' in admin_script_text
    assert '--worker-class "${CURATOR_GUNICORN_WORKER_CLASS:-gthread}"' in admin_script_text
    assert str(env_file) in admin_script_text
    assert 'error: OPENAI_API_KEY is empty after loading' in admin_script_text
    assert 'error: BUTTONDOWN_API_KEY is empty after loading' in admin_script_text
    assert '  "$@" "admin_app:app"' in admin_script_text
    assert oct(admin_script.stat().st_mode & 0o777) == "0o700"

    deliver_script_text = deliver_script.read_text(encoding="utf-8")
    assert "deliver_digest.py" in deliver_script_text
    assert 'error: OPENAI_API_KEY is empty after loading' in deliver_script_text
    assert 'error: BUTTONDOWN_API_KEY is empty after loading' in deliver_script_text
    assert "\"$@\"" in deliver_script_text

    logrotate_text = logrotate_file.read_text(encoding="utf-8")
    assert str(output_dir / "debug.ndjson") in logrotate_text
    assert "daily" in logrotate_text
    assert "rotate 7" in logrotate_text
    assert "compress" in logrotate_text
    assert "missingok" in logrotate_text
    assert "notifempty" in logrotate_text
    assert "create 0600" in logrotate_text

    daily_script_text = daily_script.read_text(encoding="utf-8")
    assert 'error: OPENAI_API_KEY is empty after loading' in daily_script_text
    assert 'error: BUTTONDOWN_API_KEY is empty after loading' in daily_script_text
    assert 'systemctl --user stop "$CURATOR_ADMIN_SERVICE_NAME"' in daily_script_text
    assert 'systemctl --user start "$CURATOR_ADMIN_SERVICE_NAME"' in daily_script_text
    assert "trap handle_exit EXIT" in daily_script_text
    assert "trap handle_interrupt INT" in daily_script_text
    assert "trap handle_terminate TERM" in daily_script_text
    assert "scripts/send_pipeline_failure_alert.py" in daily_script_text
    assert "pipeline_status=${PIPESTATUS[0]}" in daily_script_text

    cron_text = cron_file.read_text(encoding="utf-8")
    assert f"XDG_RUNTIME_DIR=/run/user/{os.getuid()}" in cron_text
    assert f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{os.getuid()}/bus" in cron_text
    assert "CRON_TZ=" not in cron_text
    assert "0 13 * * *" in cron_text
    assert str(daily_script) in cron_text
    assert str(fetch_gmail_script) not in cron_text
    assert str(fetch_sources_script) not in cron_text
    assert str(deliver_script) not in cron_text

    service_text = service_file.read_text(encoding="utf-8")
    assert f"WorkingDirectory={repo_dir}" in service_text
    assert f"EnvironmentFile={env_file}" in service_text
    assert f"ExecStart={admin_script}" in service_text

    caddy_text = caddy_file.read_text(encoding="utf-8")
    assert "http://curator.example.com {" in caddy_text
    assert "redir https://curator.example.com{uri} permanent" in caddy_text
    assert "https://curator.example.com {" in caddy_text
    assert "reverse_proxy 127.0.0.1:9090" in caddy_text
    assert 'X-Content-Type-Options "nosniff"' in caddy_text

    assert "Generated deployment assets:" in result.stdout
    assert f"- Debug log file: {output_dir / 'debug.ndjson'}" in result.stdout
    assert f"- Logrotate config: {logrotate_file}" in result.stdout
    assert f"- Generated Caddy config: {caddy_file}" in result.stdout
    assert "Caddy config not installed by default. Pass --install-caddy to install and reload it." in result.stdout
    assert "App bind host normalized for reverse proxy use: 0.0.0.0 -> 127.0.0.1" in result.stdout


def test_bootstrap_deduplicates_generated_deploy_path(tmp_path, repo_root):
    venv_bin = repo_root / ".venv" / "bin"
    duplicated_path = os.pathsep.join(
        [
            str(venv_bin),
            str(venv_bin),
            "/root/.local/bin",
            "/usr/local/bin",
            "/root/.local/bin",
            "/usr/bin",
        ]
    )

    _, paths = _run_bootstrap(tmp_path, repo_root, extra_env={"PATH": duplicated_path})

    expected_path = os.pathsep.join(
        [
            str(venv_bin),
            "/root/.local/bin",
            "/usr/local/bin",
            "/usr/bin",
        ]
    )
    assert f"PATH={expected_path}\n" in paths["env_file"].read_text(encoding="utf-8")
    assert f"PATH={expected_path}\n" in paths["cron_file"].read_text(encoding="utf-8")


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
        "systemctl --user is-active --quiet newsletter-curator-admin",
        "uv run python daily_pipeline.py --dry-run-recipient you@example.com",
        "systemctl --user start newsletter-curator-admin",
    ]


def test_bootstrap_reuses_existing_api_keys_when_flags_are_omitted(tmp_path, repo_root):
    _run_bootstrap(tmp_path, repo_root)

    result, paths = _run_bootstrap(
        tmp_path,
        repo_root,
        extra_env={
            "OPENAI_API_KEY": "",
            "BUTTONDOWN_API_KEY": "",
        },
        include_api_keys=False,
    )

    env_text = paths["env_file"].read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=test-openai-key" in env_text
    assert "BUTTONDOWN_API_KEY=test-buttondown-key" in env_text
    assert "Generated deployment assets:" in result.stdout


def test_bootstrap_adds_admin_port_to_direct_access_public_base_url(tmp_path, repo_root):
    output_dir = tmp_path / "deploy-generated"
    script_path = repo_root / "scripts" / "bootstrap_server.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--repo-dir",
            str(repo_root),
            "--output-dir",
            str(output_dir),
            "--uv-bin",
            "/usr/local/bin/uv",
            "--config-path",
            str(repo_root / "config.yaml"),
            "--app-host",
            "0.0.0.0",
            "--app-port",
            "9090",
            "--admin-token",
            "test-admin-token",
            "--debug-log-token",
            "test-debug-log-token",
            "--public-base-url",
            "http://159.65.104.249/",
            "--openai-api-key",
            "test-openai-key",
            "--buttondown-api-key",
            "test-buttondown-key",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    env_text = (output_dir / "newsletter-curator.env").read_text(encoding="utf-8")

    assert "CURATOR_PUBLIC_BASE_URL=http://159.65.104.249" in env_text
    assert "Warning: --public-base-url has no explicit port" not in result.stdout


def test_bootstrap_generates_https_raw_ip_caddy_config(tmp_path, repo_root):
    result, paths = _run_bootstrap(
        tmp_path,
        repo_root,
        app_port=9090,
        public_base_url="https://159.65.104.249",
    )

    env_text = paths["env_file"].read_text(encoding="utf-8")
    caddy_text = paths["caddy_file"].read_text(encoding="utf-8")

    assert "CURATOR_APP_PORT=9090" in env_text
    assert "CURATOR_PUBLIC_BASE_URL=https://159.65.104.249" in env_text
    assert "http://159.65.104.249 {" in caddy_text
    assert "redir https://159.65.104.249{uri} permanent" in caddy_text
    assert "https://159.65.104.249 {" in caddy_text
    assert "issuer acme {" in caddy_text
    assert "dir https://acme-v02.api.letsencrypt.org/directory" in caddy_text
    assert "profile shortlived" in caddy_text
    assert "reverse_proxy 127.0.0.1:9090" in caddy_text
    assert "App bind port normalized" not in result.stdout


def test_bootstrap_accepts_legacy_admin_host_and_port_flags(tmp_path, repo_root):
    output_dir = tmp_path / "deploy-generated"
    script_path = repo_root / "scripts" / "bootstrap_server.py"

    subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--repo-dir",
            str(repo_root),
            "--output-dir",
            str(output_dir),
            "--uv-bin",
            "/usr/local/bin/uv",
            "--config-path",
            str(repo_root / "config.yaml"),
            "--admin-host",
            "0.0.0.0",
            "--admin-port",
            "9090",
            "--admin-token",
            "test-admin-token",
            "--debug-log-token",
            "test-debug-log-token",
            "--public-base-url",
            "https://curator.example.com",
            "--openai-api-key",
            "test-openai-key",
            "--buttondown-api-key",
            "test-buttondown-key",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    env_text = (output_dir / "newsletter-curator.env").read_text(encoding="utf-8")

    assert "CURATOR_APP_HOST=127.0.0.1" in env_text
    assert "CURATOR_APP_PORT=9090" in env_text


def test_bootstrap_normalizes_internal_app_port_when_public_origin_matches_it(tmp_path, repo_root):
    result, paths = _run_bootstrap(
        tmp_path,
        repo_root,
        app_port=9090,
        public_base_url="http://159.65.104.249:9090",
    )

    env_text = paths["env_file"].read_text(encoding="utf-8")
    caddy_text = paths["caddy_file"].read_text(encoding="utf-8")

    assert "CURATOR_APP_HOST=127.0.0.1" in env_text
    assert "CURATOR_APP_PORT=9091" in env_text
    assert "CURATOR_PUBLIC_BASE_URL=http://159.65.104.249:9090" in env_text
    assert "http://159.65.104.249:9090 {" in caddy_text
    assert "reverse_proxy 127.0.0.1:9091" in caddy_text
    assert "App bind port normalized for reverse proxy use: 9090 -> 9091" in result.stdout


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
    command_lines = command_log.read_text(encoding="utf-8").splitlines()
    assert command_lines[:3] == [
        "systemctl --user stop newsletter-curator-admin",
        "systemctl --user is-active --quiet newsletter-curator-admin",
        "uv run python daily_pipeline.py",
    ]
    assert command_lines[3].startswith(
        "uv run python scripts/send_pipeline_failure_alert.py "
        "--source run_daily_pipeline.sh --exit-status 7 --output-file "
    )
    assert command_lines[4:] == [
        "systemctl --user start newsletter-curator-admin",
    ]


def test_generated_daily_wrapper_skips_entire_pipeline_on_sunday(tmp_path, repo_root):
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
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "FAKE_DATE_WEEKDAY": "7",
            "FAKE_UV_EXIT_CODE": "7",
            "FAKE_SYSTEMCTL_FAIL_STOP": "1",
        },
    )

    assert result.returncode == 0
    assert "daily pipeline skipped: Sunday" in result.stdout
    assert not command_log.exists()


def test_generated_daily_wrapper_alert_receives_pipeline_output_file(tmp_path, repo_root):
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    command_log = tmp_path / "commands.log"
    alert_capture_path = tmp_path / "alert-capture.json"
    _write_fake_runtime_with_alert_capture(fake_bin, command_log, alert_capture_path)
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
    assert "pipeline stdout before failure" in result.stdout
    assert "pipeline stderr before failure" in result.stdout

    alert_payload = json.loads(alert_capture_path.read_text(encoding="utf-8"))
    assert alert_payload["source"] == "run_daily_pipeline.sh"
    assert alert_payload["exit_status"] == "7"
    assert "pipeline stdout before failure" in alert_payload["output"]
    assert "pipeline stderr before failure" in alert_payload["output"]
    assert not Path(alert_payload["output_file"]).exists()

    command_lines = command_log.read_text(encoding="utf-8").splitlines()
    assert command_lines[:4] == [
        "systemctl --user stop newsletter-curator-admin",
        "systemctl --user is-active --quiet newsletter-curator-admin",
        "uv run python daily_pipeline.py",
        (
            "uv run python scripts/send_pipeline_failure_alert.py "
            f"--source run_daily_pipeline.sh --exit-status 7 --output-file {alert_payload['output_file']}"
        ),
    ]
    assert command_lines[4:] == [
        "systemctl --user start newsletter-curator-admin",
    ]


def test_generated_daily_wrapper_aborts_when_admin_stop_fails(tmp_path, repo_root):
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

    assert result.returncode == 1
    assert "aborting daily pipeline" in result.stderr
    assert command_log.read_text(encoding="utf-8").splitlines() == [
        "systemctl --user stop newsletter-curator-admin",
        "systemctl --user start newsletter-curator-admin",
    ]


def test_generated_daily_wrapper_aborts_when_admin_remains_active(tmp_path, repo_root):
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
            "FAKE_SYSTEMCTL_ACTIVE": "1",
            "CURATOR_ADMIN_STOP_WAIT_SECONDS": "1",
            "FAKE_UV_EXIT_CODE": "0",
        },
    )

    assert result.returncode == 1
    assert "is still active after stop" in result.stderr
    command_lines = command_log.read_text(encoding="utf-8").splitlines()
    assert command_lines[:2] == [
        "systemctl --user stop newsletter-curator-admin",
        "systemctl --user is-active --quiet newsletter-curator-admin",
    ]
    assert "uv run python daily_pipeline.py" not in command_lines
    assert command_lines[-1] == "systemctl --user start newsletter-curator-admin"


def test_generated_daily_wrapper_fails_when_api_keys_are_empty(tmp_path, repo_root):
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

    env_file = paths["env_file"]
    env_file.write_text(
        env_file.read_text(encoding="utf-8")
        .replace("OPENAI_API_KEY=test-openai-key", "OPENAI_API_KEY=")
        .replace("BUTTONDOWN_API_KEY=test-buttondown-key", "BUTTONDOWN_API_KEY="),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(paths["daily_script"])],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "FAKE_UV_EXIT_CODE": "0",
        },
    )

    assert result.returncode == 1
    assert "error: OPENAI_API_KEY is empty after loading" in result.stderr
    assert not command_log.exists()


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


def test_install_logrotate_config_is_rerunnable(tmp_path):
    logrotate_file = tmp_path / "newsletter-curator.logrotate"
    logrotate_file.write_text("/tmp/debug.ndjson {\n    daily\n}\n", encoding="utf-8")
    target_dir = tmp_path / "logrotate.d"

    installed_path = bootstrap_server.install_logrotate_config(
        logrotate_file,
        target_dir,
        "newsletter-curator-admin",
    )

    assert installed_path == target_dir / "newsletter-curator-admin"
    assert installed_path.exists()
    assert installed_path.read_text(encoding="utf-8") == logrotate_file.read_text(encoding="utf-8")


def test_install_caddy_config_is_rerunnable(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_run(cmd, check):
        calls.append(list(cmd))

    monkeypatch.setattr(bootstrap_server.subprocess, "run", fake_run)

    caddy_file = tmp_path / "newsletter-curator.Caddyfile"
    caddy_file.write_text("https://curator.example.com {\n    reverse_proxy 127.0.0.1:8080\n}\n", encoding="utf-8")
    target_path = tmp_path / "etc" / "caddy" / "Caddyfile"

    installed_path = bootstrap_server.install_caddy_config(
        caddy_file,
        target_path,
        "caddy",
    )

    assert installed_path == target_path
    assert installed_path.exists()
    assert installed_path.read_text(encoding="utf-8") == caddy_file.read_text(encoding="utf-8")
    assert calls == [["systemctl", "reload-or-restart", "caddy"]]


def test_main_restarts_admin_service_before_reloading_caddy(monkeypatch, tmp_path):
    repo_dir = tmp_path / "repo"
    output_dir = tmp_path / "generated"
    repo_dir.mkdir()

    monkeypatch.setattr(
        bootstrap_server,
        "parse_args",
        lambda: argparse.Namespace(
            repo_dir=repo_dir,
            output_dir=output_dir,
            uv_bin="/usr/local/bin/uv",
            config_path=repo_dir / "config.yaml",
            app_host="127.0.0.1",
            app_port=8080,
            admin_token="test-admin-token",
            mcp_token="",
            debug_log_token="test-debug-log-token",
            openai_api_key="test-openai-key",
            buttondown_api_key="test-buttondown-key",
            public_base_url="http://159.65.104.249:8080",
            caddyfile_path=tmp_path / "etc" / "caddy" / "Caddyfile",
            caddy_service_name="caddy",
            cron_timezone="",
            daily_schedule="0 13 * * *",
            cron_log_file=None,
            debug_log_file=None,
            logrotate_file=None,
            logrotate_dir=tmp_path / "etc" / "logrotate.d",
            logrotate_rotate_count=7,
            install_logrotate=False,
            service_name="newsletter-curator-admin",
            install_crontab=False,
            install_caddy=True,
            install_systemd_user=True,
            enable_linger=False,
            linger_user="deploy-user",
        ),
    )
    monkeypatch.setattr(bootstrap_server, "read_env_assignments", lambda path: {})

    calls: list[tuple[str, str]] = []

    def fake_install_systemd_user_service(service_file, service_name):
        calls.append(("systemd", service_name))

    def fake_install_caddy_config(caddy_file, target_path, service_name):
        calls.append(("caddy", service_name))
        return target_path

    monkeypatch.setattr(
        bootstrap_server,
        "install_systemd_user_service",
        fake_install_systemd_user_service,
    )
    monkeypatch.setattr(bootstrap_server, "install_caddy_config", fake_install_caddy_config)

    bootstrap_server.main()

    assert calls == [
        ("systemd", "newsletter-curator-admin"),
        ("caddy", "caddy"),
    ]


def test_main_enables_linger_before_user_systemd_install(monkeypatch, tmp_path):
    repo_dir = tmp_path / "repo"
    output_dir = tmp_path / "generated"
    repo_dir.mkdir()

    monkeypatch.setattr(
        bootstrap_server,
        "parse_args",
        lambda: argparse.Namespace(
            repo_dir=repo_dir,
            output_dir=output_dir,
            uv_bin="/usr/local/bin/uv",
            config_path=repo_dir / "config.yaml",
            app_host="127.0.0.1",
            app_port=8080,
            admin_token="test-admin-token",
            mcp_token="",
            debug_log_token="test-debug-log-token",
            openai_api_key="test-openai-key",
            buttondown_api_key="test-buttondown-key",
            public_base_url="",
            caddyfile_path=tmp_path / "etc" / "caddy" / "Caddyfile",
            caddy_service_name="caddy",
            cron_timezone="",
            daily_schedule="0 13 * * *",
            cron_log_file=None,
            debug_log_file=None,
            logrotate_file=None,
            logrotate_dir=tmp_path / "etc" / "logrotate.d",
            logrotate_rotate_count=7,
            install_logrotate=False,
            service_name="newsletter-curator-admin",
            install_crontab=True,
            install_caddy=False,
            install_systemd_user=True,
            enable_linger=True,
            linger_user="deploy-user",
        ),
    )
    monkeypatch.setattr(bootstrap_server, "read_env_assignments", lambda path: {})

    calls: list[tuple[str, str]] = []

    def fake_enable_user_linger(user_name):
        calls.append(("linger", user_name))

    def fake_install_crontab(cron_file):
        calls.append(("crontab", cron_file.name))

    def fake_install_systemd_user_service(service_file, service_name):
        calls.append(("systemd", service_name))

    monkeypatch.setattr(bootstrap_server, "enable_user_linger", fake_enable_user_linger)
    monkeypatch.setattr(bootstrap_server, "install_crontab", fake_install_crontab)
    monkeypatch.setattr(
        bootstrap_server,
        "install_systemd_user_service",
        fake_install_systemd_user_service,
    )

    bootstrap_server.main()

    assert calls == [
        ("linger", "deploy-user"),
        ("crontab", "newsletter-curator.cron"),
        ("systemd", "newsletter-curator-admin"),
    ]
