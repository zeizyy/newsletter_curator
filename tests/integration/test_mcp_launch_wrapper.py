from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_mcp_launch_wrapper_describes_local_command(repo_root):
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
    assert payload["target"] == "local"
    assert payload["command"][0] == sys.executable
    assert Path(payload["command"][1]).name == "newsletter_mcp_server.py"
    assert payload["command"][-2:] == ["--config-path", "../../config.yaml"]


def test_mcp_launch_wrapper_describes_ssh_command(repo_root):
    script_path = repo_root / "scripts" / "newsletter_mcp_launch.py"
    env = os.environ.copy()
    env.update(
        {
            "CURATOR_MCP_TARGET": "ssh",
            "CURATOR_MCP_SSH_HOST": "curator.example.com",
            "CURATOR_MCP_SSH_USER": "deploy",
            "CURATOR_MCP_SSH_PORT": "2222",
            "CURATOR_MCP_REMOTE_REPO_DIR": "/srv/newsletter_curator",
            "CURATOR_MCP_REMOTE_CONFIG_PATH": "/etc/newsletter/config.yaml",
        }
    )
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
    assert payload["target"] == "ssh"
    assert payload["command"][:4] == ["ssh", "-T", "-p", "2222"]
    assert payload["command"][4] == "deploy@curator.example.com"
    assert payload["command"][5] == (
        "cd /srv/newsletter_curator && exec uv run python "
        "scripts/newsletter_mcp_server.py --config-path /etc/newsletter/config.yaml"
    )
