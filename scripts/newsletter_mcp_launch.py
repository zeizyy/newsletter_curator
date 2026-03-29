from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import sys


ROOT = Path(__file__).resolve().parents[1]
SERVER_SCRIPT = ROOT / "scripts" / "newsletter_mcp_server.py"

TARGET_ENV = "CURATOR_MCP_TARGET"
SSH_HOST_ENV = "CURATOR_MCP_SSH_HOST"
SSH_USER_ENV = "CURATOR_MCP_SSH_USER"
SSH_PORT_ENV = "CURATOR_MCP_SSH_PORT"
REMOTE_REPO_ENV = "CURATOR_MCP_REMOTE_REPO_DIR"
REMOTE_CONFIG_ENV = "CURATOR_MCP_REMOTE_CONFIG_PATH"

DEFAULT_TARGET = "ssh"
DEFAULT_SSH_HOST = "159.65.104.249"
DEFAULT_SSH_USER = "root"
DEFAULT_REMOTE_REPO_DIR = "/root/newsletter_curator"
DEFAULT_REMOTE_CONFIG_PATH = "config.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Launch the Newsletter Curator MCP server either against the local repo "
            "database or over SSH against a remote host's local SQLite database."
        )
    )
    parser.add_argument(
        "--local-config-path",
        default="../../config.yaml",
        help=(
            "Config path forwarded to the local MCP server when "
            f"{TARGET_ENV}=local."
        ),
    )
    parser.add_argument(
        "--describe-command",
        action="store_true",
        help="Print the resolved launch command as JSON instead of exec'ing it.",
    )
    return parser


def _require_env(env: dict[str, str], name: str) -> str:
    value = str(env.get(name, "")).strip()
    if not value:
        raise ValueError(f"{name} is required when {TARGET_ENV}=ssh.")
    return value


def _validate_ssh_host(raw_host: str) -> str:
    ssh_host = raw_host.strip()
    if ssh_host.startswith(("http://", "https://")):
        raise ValueError(
            f"{SSH_HOST_ENV} must be an SSH host or IP, not a URL: {ssh_host}"
        )
    return ssh_host


def _build_remote_command(remote_repo_dir: str, remote_config_path: str) -> str:
    return (
        f"cd {shlex.quote(remote_repo_dir)} && "
        "exec uv run python scripts/newsletter_mcp_server.py "
        f"--config-path {shlex.quote(remote_config_path)}"
    )


def build_launch_command(
    *,
    local_config_path: str,
    env: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    env = dict(env or os.environ)
    target = str(env.get(TARGET_ENV, DEFAULT_TARGET)).strip().lower() or DEFAULT_TARGET

    if target == "local":
        return target, [
            sys.executable,
            str(SERVER_SCRIPT),
            "--config-path",
            local_config_path,
        ]

    if target != "ssh":
        raise ValueError(f"Unsupported {TARGET_ENV} value: {target}")

    ssh_host = _validate_ssh_host(str(env.get(SSH_HOST_ENV, DEFAULT_SSH_HOST)))
    remote_repo_dir = str(env.get(REMOTE_REPO_ENV, DEFAULT_REMOTE_REPO_DIR)).strip()
    remote_config_path = (
        str(env.get(REMOTE_CONFIG_ENV, DEFAULT_REMOTE_CONFIG_PATH)).strip()
        or DEFAULT_REMOTE_CONFIG_PATH
    )
    ssh_user = str(env.get(SSH_USER_ENV, DEFAULT_SSH_USER)).strip() or DEFAULT_SSH_USER
    ssh_port = str(env.get(SSH_PORT_ENV, "")).strip()
    if not remote_repo_dir:
        raise ValueError(f"{REMOTE_REPO_ENV} must not be empty when {TARGET_ENV}=ssh.")

    destination = ssh_host if not ssh_user else f"{ssh_user}@{ssh_host}"
    command = ["ssh", "-T"]
    if ssh_port:
        command.extend(["-p", ssh_port])
    command.extend([destination, _build_remote_command(remote_repo_dir, remote_config_path)])
    return target, command


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target, command = build_launch_command(local_config_path=args.local_config_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.describe_command:
        json.dump({"target": target, "command": command}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    os.execvp(command[0], command)


if __name__ == "__main__":
    raise SystemExit(main())
