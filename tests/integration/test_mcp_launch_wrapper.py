from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_mcp_launch_wrapper_describes_local_command(repo_root):
    script_path = repo_root / "scripts" / "newsletter_mcp_launch.py"
    env = os.environ.copy()
    env["CURATOR_MCP_TARGET"] = "local"
    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--describe-command",
            "--local-config-path",
            "../../config.yaml",
        ],
        cwd=repo_root / "plugins" / "newsletter-curator-story-feed",
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    payload = json.loads(result.stdout)
    assert payload["target"] == "local"
    assert payload["command"][0] == sys.executable
    assert Path(payload["command"][1]).name == "newsletter_mcp_server.py"
    assert payload["command"][-2:] == ["--config-path", "../../config.yaml"]


def test_mcp_launch_wrapper_describes_default_production_ssh_command(repo_root):
    script_path = repo_root / "scripts" / "newsletter_mcp_launch.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--describe-command",
            "--local-config-path",
            "../../config.yaml",
        ],
        cwd=repo_root / "plugins" / "newsletter-curator-story-feed",
        capture_output=True,
        text=True,
        check=True,
        env=os.environ.copy(),
    )

    payload = json.loads(result.stdout)
    assert payload["target"] == "ssh"
    assert payload["command"][:2] == ["ssh", "-T"]
    assert payload["command"][2] == "root@159.65.104.249"
    assert payload["command"][3] == (
        "cd /root/newsletter_curator && exec uv run python "
        "scripts/newsletter_mcp_server.py --config-path config.yaml"
    )


def test_mcp_launch_wrapper_rejects_url_shaped_ssh_host(repo_root):
    script_path = repo_root / "scripts" / "newsletter_mcp_launch.py"
    env = os.environ.copy()
    env["CURATOR_MCP_SSH_HOST"] = "http://159.65.104.249"
    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--describe-command",
        ],
        cwd=repo_root / "plugins" / "newsletter-curator-story-feed",
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "must be an SSH host or IP, not a URL" in result.stderr
