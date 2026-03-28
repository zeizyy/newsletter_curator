from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from tests.helpers import write_temp_config


def _send_message(process: subprocess.Popen[str], payload: dict) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _read_message(process: subprocess.Popen[str]) -> dict:
    assert process.stdout is not None
    line = process.stdout.readline()
    if line:
        return json.loads(line)
    stderr_output = process.stderr.read() if process.stderr is not None else ""
    raise AssertionError(f"Server exited before responding. stderr={stderr_output!r}")


def test_newsletter_mcp_server_help_output(repo_root):
    script_path = repo_root / "scripts" / "newsletter_mcp_server.py"
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "newline-delimited stdio JSON-RPC" in result.stdout
    assert "--config-path" in result.stdout
    assert "NEWSLETTER_CONFIG" in result.stdout


def test_newsletter_mcp_server_initialize_smoke(tmp_path, repo_root):
    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    script_path = repo_root / "scripts" / "newsletter_mcp_server.py"
    process = subprocess.Popen(
        [sys.executable, str(script_path), "--config-path", str(config_path)],
        cwd=repo_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
    )
    try:
        _send_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0.0.0"},
                },
            },
        )
        response = _read_message(process)
    finally:
        if process.stdin is not None:
            process.stdin.close()
        process.terminate()
        process.wait(timeout=5)

    assert response["result"]["protocolVersion"] == "2025-11-25"
    assert response["result"]["serverInfo"]["name"] == "newsletter-curator-story-feed"
