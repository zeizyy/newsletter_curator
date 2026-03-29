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
            f"{TARGET_ENV}=local or unset."
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
    target = str(env.get(TARGET_ENV, "local")).strip().lower() or "local"

    if target == "local":
        return target, [
            sys.executable,
            str(SERVER_SCRIPT),
            "--config-path",
            local_config_path,
        ]

    if target != "ssh":
        raise ValueError(f"Unsupported {TARGET_ENV} value: {target}")

    ssh_host = _require_env(env, SSH_HOST_ENV)
    remote_repo_dir = _require_env(env, REMOTE_REPO_ENV)
    remote_config_path = str(env.get(REMOTE_CONFIG_ENV, "config.yaml")).strip() or "config.yaml"
    ssh_user = str(env.get(SSH_USER_ENV, "")).strip()
    ssh_port = str(env.get(SSH_PORT_ENV, "")).strip()

    destination = ssh_host if not ssh_user else f"{ssh_user}@{ssh_host}"
    command = ["ssh", "-T"]
    if ssh_port:
        command.extend(["-p", ssh_port])
    command.extend([destination, _build_remote_command(remote_repo_dir, remote_config_path)])
    return target, command


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target, command = build_launch_command(local_config_path=args.local_config_path)
    if args.describe_command:
        json.dump({"target": target, "command": command}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    os.execvp(command[0], command)


if __name__ == "__main__":
    raise SystemExit(main())
