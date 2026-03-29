from __future__ import annotations

import json
import subprocess
import sys


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


def test_mcp_publish_manifest(repo_root):
    plugin_root = repo_root / "plugins" / "newsletter-curator-story-feed"
    plugin_manifest = json.loads(
        (plugin_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    mcp_manifest = json.loads((plugin_root / ".mcp.json").read_text(encoding="utf-8"))
    marketplace = json.loads(
        (repo_root / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )

    assert plugin_manifest["name"] == "newsletter-curator-story-feed"
    assert plugin_manifest["mcpServers"] == "./.mcp.json"
    assert plugin_manifest["interface"]["displayName"] == "Newsletter Story Feed"

    server = mcp_manifest["mcpServers"]["newsletter-curator-story-feed"]
    assert server["type"] == "stdio"
    assert server["command"] == "uv"
    assert "../../scripts/newsletter_mcp_launch.py" in server["args"]
    assert "../../config.yaml" in server["args"]

    entry = marketplace["plugins"][0]
    assert marketplace["name"] == "newsletter-curator-local"
    assert entry["name"] == "newsletter-curator-story-feed"
    assert entry["source"]["path"] == "./plugins/newsletter-curator-story-feed"
    assert entry["policy"]["installation"] == "AVAILABLE"
    assert entry["policy"]["authentication"] == "ON_INSTALL"

    process = subprocess.Popen(
        [server["command"], *server["args"]],
        cwd=plugin_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
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
