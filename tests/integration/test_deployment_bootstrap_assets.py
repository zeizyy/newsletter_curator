from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path


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
            "--cron-timezone",
            "America/Los_Angeles",
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
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"

    admin_script_text = admin_script.read_text(encoding="utf-8")
    assert "admin_app.py" in admin_script_text
    assert str(env_file) in admin_script_text
    assert oct(admin_script.stat().st_mode & 0o777) == "0o700"

    cron_text = cron_file.read_text(encoding="utf-8")
    assert "CRON_TZ=America/Los_Angeles" in cron_text
    assert "15 16 * * *" in cron_text
    assert str(daily_script) in cron_text
    assert str(fetch_gmail_script) not in cron_text
    assert str(fetch_sources_script) not in cron_text
    assert str(deliver_script) not in cron_text

    service_text = service_file.read_text(encoding="utf-8")
    assert f"WorkingDirectory={repo_dir}" in service_text
    assert f"EnvironmentFile={env_file}" in service_text
    assert f"ExecStart={admin_script}" in service_text

    assert "Generated deployment assets:" in result.stdout
