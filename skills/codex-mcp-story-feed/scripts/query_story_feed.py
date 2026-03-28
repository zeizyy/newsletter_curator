#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Query the published Newsletter Curator MCP plugin and print the "
            "structured recent-story payload as JSON."
        )
    )
    parser.add_argument("--hours", type=int, default=24, help="Recent-story window in hours.")
    parser.add_argument("--source-type", default="", help="Optional exact-match source_type filter.")
    parser.add_argument(
        "--config-path",
        default="",
        help="Optional config path override forwarded to the plugin's MCP launch command.",
    )
    return parser


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def plugin_root() -> Path:
    return repo_root() / "plugins" / "newsletter-curator-story-feed"


def load_server_config() -> dict:
    manifest_path = plugin_root() / ".mcp.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return payload["mcpServers"]["newsletter-curator-story-feed"]


def build_server_command(server_config: dict, *, config_path: str) -> list[str]:
    command = [str(server_config["command"]), *list(server_config.get("args", []))]
    if not config_path:
        return command

    if "--config-path" in command:
        index = command.index("--config-path")
        if index + 1 < len(command):
            command[index + 1] = config_path
            return command
    command.extend(["--config-path", config_path])
    return command


def send_message(process: subprocess.Popen[str], payload: dict) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def read_message(process: subprocess.Popen[str]) -> dict:
    assert process.stdout is not None
    line = process.stdout.readline()
    if line:
        return json.loads(line)
    stderr_output = process.stderr.read() if process.stderr is not None else ""
    raise RuntimeError(f"MCP server exited before responding. stderr={stderr_output!r}")


def query_story_feed(*, hours: int, source_type: str, config_path: str) -> dict:
    server_config = load_server_config()
    command = build_server_command(server_config, config_path=config_path)
    process = subprocess.Popen(
        command,
        cwd=plugin_root(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        send_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "codex-mcp-story-feed-script", "version": "0.1.0"},
                },
            },
        )
        _ = read_message(process)
        send_message(
            process,
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        arguments: dict[str, object] = {"hours": hours}
        if source_type.strip():
            arguments["source_type"] = source_type.strip()
        send_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "list_recent_stories", "arguments": arguments},
            },
        )
        response = read_message(process)
    finally:
        if process.stdin is not None:
            process.stdin.close()
        process.terminate()
        process.wait(timeout=5)

    result = response["result"]
    if result.get("isError"):
        message = result.get("content", [{}])[0].get("text", "Unknown MCP tool error.")
        raise RuntimeError(str(message))
    return result["structuredContent"]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = query_story_feed(
        hours=args.hours,
        source_type=args.source_type,
        config_path=args.config_path,
    )
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
