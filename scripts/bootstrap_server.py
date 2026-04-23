#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import grp
import ipaddress
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_DEPLOY_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and optionally install server bootstrap assets for Newsletter Curator."
    )
    parser.add_argument("--repo-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--uv-bin", default=shutil.which("uv") or "uv")
    parser.add_argument("--config-path", type=Path, default=None)
    parser.add_argument(
        "--app-host",
        "--admin-host",
        dest="app_host",
        default=os.getenv("CURATOR_APP_HOST", os.getenv("CURATOR_ADMIN_HOST", "127.0.0.1")),
        help="HTTP app bind host. --admin-host remains accepted as a deprecated alias.",
    )
    parser.add_argument(
        "--app-port",
        "--admin-port",
        dest="app_port",
        type=int,
        default=int(os.getenv("CURATOR_APP_PORT", os.getenv("CURATOR_ADMIN_PORT", "8080"))),
        help="HTTP app bind port. --admin-port remains accepted as a deprecated alias.",
    )
    parser.add_argument("--admin-token", default=os.getenv("CURATOR_ADMIN_TOKEN", ""))
    parser.add_argument(
        "--mcp-token",
        default=os.getenv("CURATOR_MCP_TOKEN", ""),
        help=(
            "Bearer token for the remote HTTP /mcp endpoint. "
            "Defaults to CURATOR_MCP_TOKEN, and falls back to --admin-token when omitted."
        ),
    )
    parser.add_argument(
        "--debug-log-token",
        default=os.getenv("CURATOR_DEBUG_LOG_TOKEN", ""),
        help=(
            "Dedicated bearer or URL token for the read-only /debug/logs endpoint. "
            "Leave empty to keep the endpoint disabled."
        ),
    )
    parser.add_argument("--openai-api-key", default=os.getenv("OPENAI_API_KEY", ""))
    parser.add_argument("--buttondown-api-key", default=os.getenv("BUTTONDOWN_API_KEY", ""))
    parser.add_argument("--public-base-url", default=os.getenv("CURATOR_PUBLIC_BASE_URL", ""))
    parser.add_argument(
        "--caddyfile-path",
        type=Path,
        default=Path("/etc/caddy/Caddyfile"),
        help="Target path for the generated Caddy config when --install-caddy is used.",
    )
    parser.add_argument(
        "--caddy-service-name",
        default="caddy",
        help="Systemd service name to reload after installing the Caddy config.",
    )
    parser.add_argument("--cron-timezone", default="")
    parser.add_argument("--daily-schedule", default="30 13 * * *")
    parser.add_argument("--cron-log-file", type=Path, default=None)
    parser.add_argument("--debug-log-file", type=Path, default=None)
    parser.add_argument("--logrotate-file", type=Path, default=None)
    parser.add_argument("--logrotate-dir", type=Path, default=Path("/etc/logrotate.d"))
    parser.add_argument("--logrotate-rotate-count", type=int, default=7)
    parser.add_argument("--install-logrotate", action="store_true")
    parser.add_argument("--service-name", default="newsletter-curator-admin")
    parser.add_argument("--install-crontab", action="store_true")
    parser.add_argument(
        "--install-caddy",
        action="store_true",
        help="Install the generated Caddy config and reload the configured Caddy service.",
    )
    parser.add_argument(
        "--install-systemd-user",
        action="store_true",
        help="Opt in to installing and starting the admin app systemd --user service.",
    )
    parser.add_argument("--enable-linger", action="store_true")
    parser.add_argument("--linger-user", default=os.getenv("USER") or getpass.getuser())
    return parser.parse_args()


def quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def write_file(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def read_env_assignments(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    assignments: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        assignments[key.strip()] = value
    return assignments


def dedupe_path_entries(entries: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        normalized = str(entry or "").strip()
        if not normalized or normalized in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized)
    return deduped


def build_deploy_path(repo_dir: Path, current_path: str | None = None) -> str:
    path_value = os.getenv("PATH", DEFAULT_DEPLOY_PATH) if current_path is None else current_path
    base_entries = path_value.split(os.pathsep) if path_value else DEFAULT_DEPLOY_PATH.split(os.pathsep)
    entries = [str(repo_dir / ".venv" / "bin"), *base_entries]
    return os.pathsep.join(dedupe_path_entries(entries))


def systemd_user_runtime_dir(uid: int | None = None) -> str:
    return f"/run/user/{os.getuid() if uid is None else uid}"


def build_env_file(
    *,
    repo_dir: Path,
    config_path: Path,
    app_host: str,
    app_port: int,
    admin_token: str,
    mcp_token: str,
    debug_log_token: str,
    debug_log_path: Path,
    admin_service_name: str,
    openai_api_key: str,
    buttondown_api_key: str,
    public_base_url: str,
) -> str:
    runtime_dir = systemd_user_runtime_dir()
    return "\n".join(
        [
            "# Generated by scripts/bootstrap_server.py",
            f"NEWSLETTER_CONFIG={config_path}",
            f"CURATOR_APP_HOST={app_host}",
            f"CURATOR_APP_PORT={app_port}",
            f"CURATOR_ADMIN_TOKEN={admin_token}",
            f"CURATOR_MCP_TOKEN={mcp_token}",
            f"CURATOR_DEBUG_LOG_TOKEN={debug_log_token}",
            f"CURATOR_DEBUG_LOG_PATH={debug_log_path}",
            f"CURATOR_ADMIN_SERVICE_NAME={admin_service_name}",
            "CURATOR_PAUSE_ADMIN_DURING_DAILY=1",
            "CURATOR_TRUST_PROXY_HEADERS=1",
            "CURATOR_GUNICORN_WORKERS=1",
            "CURATOR_GUNICORN_WORKER_CLASS=gthread",
            "CURATOR_GUNICORN_THREADS=4",
            "CURATOR_GUNICORN_TIMEOUT=120",
            "CURATOR_GUNICORN_GRACEFUL_TIMEOUT=30",
            f"OPENAI_API_KEY={openai_api_key}",
            f"BUTTONDOWN_API_KEY={buttondown_api_key}",
            f"CURATOR_PUBLIC_BASE_URL={public_base_url}",
            f"XDG_RUNTIME_DIR={runtime_dir}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime_dir}/bus",
            f"PATH={build_deploy_path(repo_dir)}",
            "",
        ]
    )


def normalize_app_bind_host(app_host: str, public_base_url: str) -> str:
    normalized_host = str(app_host or "").strip() or "127.0.0.1"
    if not str(public_base_url or "").strip():
        return normalized_host
    if normalized_host == "0.0.0.0":
        return "127.0.0.1"
    if normalized_host == "::":
        return "::1"
    return normalized_host


def normalize_app_bind_port(app_port: int, public_base_url: str) -> int:
    normalized_port = int(app_port)
    configured = normalize_public_base_url(public_base_url)
    if not configured:
        return normalized_port
    parsed = urlparse(configured)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return normalized_port
    public_port = parsed.port
    if public_port is None:
        public_port = 443 if parsed.scheme == "https" else 80
    if public_port != normalized_port:
        return normalized_port
    if normalized_port >= 65535:
        return 65534
    return max(1, normalized_port + 1)


def normalize_public_base_url(public_base_url: str) -> str:
    configured = str(public_base_url or "").strip()
    if not configured:
        return ""
    return configured.rstrip("/")


def public_base_url_warning(public_base_url: str) -> str:
    configured = str(public_base_url or "").strip()
    if not configured:
        return ""
    parsed = urlparse(configured)
    if not parsed.scheme or not parsed.netloc:
        return "Warning: --public-base-url should be an absolute http:// or https:// URL."
    if parsed.path not in {"", "/"}:
        return "Warning: --public-base-url should be an origin only; path components are ignored by Caddy."
    return ""


def build_runner_script(*, repo_dir: Path, env_file: Path, uv_bin: str, entrypoint: str) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"cd {quote(repo_dir)}",
            "set -a",
            f"source {quote(env_file)}",
            "set +a",
            "",
            f'if [[ -z "${{OPENAI_API_KEY:-}}" ]]; then',
            f'  echo "error: OPENAI_API_KEY is empty after loading {quote(env_file)}" >&2',
            "  exit 1",
            "fi",
            f'if [[ -z "${{BUTTONDOWN_API_KEY:-}}" ]]; then',
            f'  echo "error: BUTTONDOWN_API_KEY is empty after loading {quote(env_file)}" >&2',
            "  exit 1",
            "fi",
            f"exec {quote(uv_bin)} run python {quote(entrypoint)} \"$@\"",
            "",
        ]
    )


def build_admin_runner_script(*, repo_dir: Path, env_file: Path, uv_bin: str) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"cd {quote(repo_dir)}",
            "set -a",
            f"source {quote(env_file)}",
            "set +a",
            "",
            f'if [[ -z "${{OPENAI_API_KEY:-}}" ]]; then',
            f'  echo "error: OPENAI_API_KEY is empty after loading {quote(env_file)}" >&2',
            "  exit 1",
            "fi",
            f'if [[ -z "${{BUTTONDOWN_API_KEY:-}}" ]]; then',
            f'  echo "error: BUTTONDOWN_API_KEY is empty after loading {quote(env_file)}" >&2',
            "  exit 1",
            "fi",
            f"exec {quote(uv_bin)} run gunicorn \\",
            '  --bind "${CURATOR_APP_HOST:-127.0.0.1}:${CURATOR_APP_PORT:-8080}" \\',
            '  --workers "${CURATOR_GUNICORN_WORKERS:-1}" \\',
            '  --worker-class "${CURATOR_GUNICORN_WORKER_CLASS:-gthread}" \\',
            '  --threads "${CURATOR_GUNICORN_THREADS:-4}" \\',
            '  --timeout "${CURATOR_GUNICORN_TIMEOUT:-120}" \\',
            '  --graceful-timeout "${CURATOR_GUNICORN_GRACEFUL_TIMEOUT:-30}" \\',
            "  --access-logfile - \\",
            "  --error-logfile - \\",
            "  --capture-output \\",
            '  "$@" "admin_app:app"',
            "",
        ]
    )


def build_logrotate_config(
    *,
    debug_log_path: Path,
    rotate_count: int,
    owner: str,
    group: str,
) -> str:
    return "\n".join(
        [
            f"{debug_log_path} {{",
            "    daily",
            f"    rotate {max(1, int(rotate_count))}",
            "    compress",
            "    missingok",
            "    notifempty",
            f"    create 0600 {owner} {group}",
            "}",
            "",
        ]
    )


def _normalize_reverse_proxy_host(app_host: str) -> str:
    normalized_host = str(app_host or "").strip() or "127.0.0.1"
    if normalized_host == "0.0.0.0":
        return "127.0.0.1"
    if normalized_host == "::":
        return "::1"
    return normalized_host


def _hostname_is_ip(hostname: str) -> bool:
    try:
        ipaddress.ip_address(str(hostname or "").strip())
    except ValueError:
        return False
    return True


def build_caddyfile(*, public_base_url: str, app_host: str, app_port: int) -> str:
    configured = normalize_public_base_url(public_base_url)
    parsed = urlparse(configured)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--public-base-url must be an absolute http:// or https:// URL.")
    if parsed.path not in {"", "/"}:
        raise ValueError("--public-base-url must not include a path component.")

    upstream_host = _normalize_reverse_proxy_host(app_host)
    if ":" in upstream_host and not upstream_host.startswith("["):
        upstream_host = f"[{upstream_host}]"
    upstream = f"{upstream_host}:{app_port}"
    site_label = f"{parsed.scheme}://{parsed.netloc}"
    lines = [
        f"{site_label} {{",
        *(
            [
                "    tls {",
                "        issuer acme {",
                "            dir https://acme-v02.api.letsencrypt.org/directory",
                "            profile shortlived",
                "        }",
                "    }",
            ]
            if parsed.scheme == "https" and _hostname_is_ip(parsed.hostname or "")
            else []
        ),
        "    encode zstd gzip",
        "    header {",
        '        X-Content-Type-Options "nosniff"',
        '        Referrer-Policy "strict-origin-when-cross-origin"',
        '        X-Frame-Options "DENY"',
        "    }",
        f"    reverse_proxy {upstream}",
        "}",
        "",
    ]
    if parsed.scheme == "https":
        lines = [
            f"http://{parsed.netloc} {{",
            f"    redir https://{parsed.netloc}{{uri}} permanent",
            "}",
            "",
            *lines,
        ]
    return "\n".join(lines)


def build_daily_runner_script(*, repo_dir: Path, env_file: Path, uv_bin: str) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"cd {quote(repo_dir)}",
            "set -a",
            f"source {quote(env_file)}",
            "set +a",
            "",
            "manual_lookback_days=0",
            'for arg in "$@"; do',
            '  if [[ "$arg" == "--lookback_days" ]] || [[ "$arg" == "--lookback-days" ]] || [[ "$arg" == --lookback_days=* ]] || [[ "$arg" == --lookback-days=* ]]; then',
            "    manual_lookback_days=1",
            "  fi",
            "done",
            "",
            'current_weekday="$(TZ=America/Los_Angeles date +%u)"',
            'if [[ "$current_weekday" == "7" ]] && [[ "$manual_lookback_days" -ne 1 ]]; then',
            '  echo "daily pipeline skipped: Sunday"',
            "  exit 0",
            "fi",
            "",
            f'if [[ -z "${{OPENAI_API_KEY:-}}" ]]; then',
            f'  echo "error: OPENAI_API_KEY is empty after loading {quote(env_file)}" >&2',
            "  exit 1",
            "fi",
            f'if [[ -z "${{BUTTONDOWN_API_KEY:-}}" ]]; then',
            f'  echo "error: BUTTONDOWN_API_KEY is empty after loading {quote(env_file)}" >&2',
            "  exit 1",
            "fi",
            "",
            'should_manage_admin=0',
            'if [[ "${CURATOR_PAUSE_ADMIN_DURING_DAILY:-0}" =~ ^(1|true|yes|on)$ ]] && [[ -n "${CURATOR_ADMIN_SERVICE_NAME:-}" ]]; then',
            "  should_manage_admin=1",
            "fi",
            "",
            "admin_resumed=0",
            'pipeline_output=""',
            "cleanup_pipeline_output() {",
            '  if [[ -n "$pipeline_output" ]]; then',
            '    rm -f "$pipeline_output"',
            "  fi",
            "}",
            "",
            "resume_admin_service() {",
            '  if [[ "$should_manage_admin" -ne 1 ]] || [[ "$admin_resumed" -eq 1 ]]; then',
            "    return 0",
            "  fi",
            "  admin_resumed=1",
            '  systemctl --user start "$CURATOR_ADMIN_SERVICE_NAME" || \\',
            '    echo "warning: failed to restart admin service $CURATOR_ADMIN_SERVICE_NAME" >&2',
            "}",
            "",
            "handle_exit() {",
            "  cleanup_pipeline_output",
            "  resume_admin_service",
            "}",
            "",
            "handle_interrupt() {",
            "  resume_admin_service",
            "  exit 130",
            "}",
            "",
            "handle_terminate() {",
            "  resume_admin_service",
            "  exit 143",
            "}",
            "",
            "trap handle_exit EXIT",
            "trap handle_interrupt INT",
            "trap handle_terminate TERM",
            "",
            "pause_admin_service() {",
            '  if [[ "$should_manage_admin" -ne 1 ]]; then',
            "    return 0",
            "  fi",
            '  if ! systemctl --user stop "$CURATOR_ADMIN_SERVICE_NAME"; then',
            '    echo "error: failed to stop admin service $CURATOR_ADMIN_SERVICE_NAME; aborting daily pipeline" >&2',
            "    return 1",
            "  fi",
            '  stop_wait_seconds="${CURATOR_ADMIN_STOP_WAIT_SECONDS:-10}"',
            '  if ! [[ "$stop_wait_seconds" =~ ^[0-9]+$ ]]; then',
            "    stop_wait_seconds=10",
            "  fi",
            '  for ((attempt = 0; attempt < stop_wait_seconds; attempt++)); do',
            '    if ! systemctl --user is-active --quiet "$CURATOR_ADMIN_SERVICE_NAME"; then',
            "      return 0",
            "    fi",
            "    sleep 1",
            "  done",
            '  echo "error: admin service $CURATOR_ADMIN_SERVICE_NAME is still active after stop; aborting daily pipeline" >&2',
            "  return 1",
            "}",
            "",
            "pause_admin_service",
            "",
            'pipeline_output="$(mktemp "${TMPDIR:-/tmp}/newsletter-curator-daily-output.XXXXXX")"',
            'declare -a pipeline_args=("$@")',
            "run_pipeline_attempt() {",
            "  local attempt_number=\"$1\"",
            f"  local -a pipeline_command=({quote(uv_bin)} run python daily_pipeline.py)",
            '  if (( ${#pipeline_args[@]} > 0 )); then',
            '    pipeline_command+=("${pipeline_args[@]}")',
            "  fi",
            '  echo "daily pipeline attempt ${attempt_number}/2"',
            "  set +e",
            '  "${pipeline_command[@]}" 2>&1 | tee -a "$pipeline_output"',
            "  pipeline_status=${PIPESTATUS[0]}",
            "  set -e",
            "}",
            "",
            "pipeline_status=0",
            "run_pipeline_attempt 1",
            'if [[ "$pipeline_status" -ne 0 ]]; then',
            '  echo "warning: daily pipeline failed with status $pipeline_status; retrying once" >&2',
            "  run_pipeline_attempt 2",
            "fi",
            'if [[ "$pipeline_status" -ne 0 ]]; then',
            (
                f"  if ! {quote(uv_bin)} run python scripts/send_pipeline_failure_alert.py "
                '--source "run_daily_pipeline.sh" '
                '--exit-status "$pipeline_status" '
                '--output-file "$pipeline_output"; then'
            ),
            '    echo "warning: failed to send daily pipeline failure alert" >&2',
            "  fi",
            "fi",
            "exit \"$pipeline_status\"",
            "",
        ]
    )


def build_cron_file(
    *,
    repo_dir: Path,
    cron_timezone: str,
    daily_schedule: str,
    log_file: Path,
    daily_script: Path,
) -> str:
    runtime_dir = systemd_user_runtime_dir()
    lines = [
        "SHELL=/bin/bash",
        f"XDG_RUNTIME_DIR={runtime_dir}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime_dir}/bus",
        f"PATH={build_deploy_path(repo_dir)}",
    ]
    if str(cron_timezone).strip():
        lines.append(f"CRON_TZ={cron_timezone}")
    lines.extend(
        [
            "",
            f"{daily_schedule} {quote(daily_script)} >> {quote(log_file)} 2>&1",
            "",
        ]
    )
    return "\n".join(lines)


def build_systemd_service(
    *,
    service_name: str,
    repo_dir: Path,
    env_file: Path,
    admin_script: Path,
) -> str:
    return "\n".join(
        [
            "[Unit]",
            f"Description={service_name}",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"WorkingDirectory={repo_dir}",
            f"EnvironmentFile={env_file}",
            f"ExecStart={admin_script}",
            "Restart=always",
            "RestartSec=5",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def install_systemd_user_service(service_file: Path, service_name: str) -> None:
    target_dir = Path.home() / ".config" / "systemd" / "user"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{service_name}.service"
    write_file(target_path, service_file.read_text(encoding="utf-8"))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", service_name], check=True)
    subprocess.run(["systemctl", "--user", "restart", service_name], check=True)


def enable_user_linger(user_name: str) -> None:
    subprocess.run(["loginctl", "enable-linger", user_name], check=True)


def install_crontab(cron_file: Path) -> None:
    subprocess.run(["crontab", str(cron_file)], check=True)


def install_logrotate_config(logrotate_file: Path, target_dir: Path, service_name: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / service_name
    write_file(target_path, logrotate_file.read_text(encoding="utf-8"))
    return target_path


def install_caddy_config(caddy_file: Path, target_path: Path, service_name: str) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    write_file(target_path, caddy_file.read_text(encoding="utf-8"))
    subprocess.run(["systemctl", "reload-or-restart", service_name], check=True)
    return target_path


def main() -> None:
    args = parse_args()
    if not str(args.mcp_token or "").strip():
        args.mcp_token = args.admin_token
    normalized_public_base_url = normalize_public_base_url(args.public_base_url)
    repo_dir = args.repo_dir.resolve()
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else (repo_dir / "deploy" / "generated").resolve()
    )
    config_path = (args.config_path or (repo_dir / "config.yaml")).resolve()
    log_file = (args.cron_log_file or (repo_dir / "deploy" / "generated" / "cron.log")).resolve()
    normalized_app_host = normalize_app_bind_host(args.app_host, normalized_public_base_url)
    normalized_app_port = normalize_app_bind_port(args.app_port, normalized_public_base_url)

    output_dir.mkdir(parents=True, exist_ok=True)

    env_file = output_dir / "newsletter-curator.env"
    existing_env = read_env_assignments(env_file)
    openai_api_key = str(args.openai_api_key or "").strip() or existing_env.get("OPENAI_API_KEY", "")
    buttondown_api_key = (
        str(args.buttondown_api_key or "").strip() or existing_env.get("BUTTONDOWN_API_KEY", "")
    )
    debug_log_token = (
        str(args.debug_log_token or "").strip() or existing_env.get("CURATOR_DEBUG_LOG_TOKEN", "")
    )
    debug_log_path = (
        args.debug_log_file.resolve()
        if args.debug_log_file is not None
        else Path(
            existing_env.get(
                "CURATOR_DEBUG_LOG_PATH",
                str((output_dir / "debug.ndjson").resolve()),
            )
        ).expanduser().resolve()
    )
    logrotate_file = (
        args.logrotate_file.resolve()
        if args.logrotate_file is not None
        else (output_dir / "newsletter-curator.logrotate").resolve()
    )
    logrotate_owner = getpass.getuser()
    logrotate_group = grp.getgrgid(os.getgid()).gr_name
    admin_script = output_dir / "start_admin_server.sh"
    daily_script = output_dir / "run_daily_pipeline.sh"
    fetch_gmail_script = output_dir / "run_fetch_gmail.sh"
    fetch_sources_script = output_dir / "run_fetch_sources.sh"
    deliver_script = output_dir / "run_deliver_digest.sh"
    cron_file = output_dir / "newsletter-curator.cron"
    service_file = output_dir / f"{args.service_name}.service"
    caddy_file = output_dir / "newsletter-curator.Caddyfile"

    write_file(
        env_file,
        build_env_file(
            repo_dir=repo_dir,
            config_path=config_path,
            app_host=normalized_app_host,
            app_port=normalized_app_port,
            admin_token=args.admin_token,
            mcp_token=args.mcp_token,
            debug_log_token=debug_log_token,
            debug_log_path=debug_log_path,
            admin_service_name=args.service_name,
            openai_api_key=openai_api_key,
            buttondown_api_key=buttondown_api_key,
            public_base_url=normalized_public_base_url,
        ),
        mode=0o600,
    )
    write_file(
        admin_script,
        build_admin_runner_script(
            repo_dir=repo_dir,
            env_file=env_file,
            uv_bin=args.uv_bin,
        ),
        mode=0o700,
    )
    write_file(
        daily_script,
        build_daily_runner_script(
            repo_dir=repo_dir,
            env_file=env_file,
            uv_bin=args.uv_bin,
        ),
        mode=0o700,
    )
    write_file(
        fetch_gmail_script,
        build_runner_script(
            repo_dir=repo_dir,
            env_file=env_file,
            uv_bin=args.uv_bin,
            entrypoint="fetch_gmail.py",
        ),
        mode=0o700,
    )
    write_file(
        fetch_sources_script,
        build_runner_script(
            repo_dir=repo_dir,
            env_file=env_file,
            uv_bin=args.uv_bin,
            entrypoint="fetch_sources.py",
        ),
        mode=0o700,
    )
    write_file(
        deliver_script,
        build_runner_script(
            repo_dir=repo_dir,
            env_file=env_file,
            uv_bin=args.uv_bin,
            entrypoint="deliver_digest.py",
        ),
        mode=0o700,
    )
    write_file(
        logrotate_file,
        build_logrotate_config(
            debug_log_path=debug_log_path,
            rotate_count=args.logrotate_rotate_count,
            owner=logrotate_owner,
            group=logrotate_group,
        ),
        mode=0o644,
    )
    write_file(
        cron_file,
        build_cron_file(
            repo_dir=repo_dir,
            cron_timezone=args.cron_timezone,
            daily_schedule=args.daily_schedule,
            log_file=log_file,
            daily_script=daily_script,
        ),
        mode=0o600,
    )
    write_file(
        service_file,
        build_systemd_service(
            service_name=args.service_name,
            repo_dir=repo_dir,
            env_file=env_file,
            admin_script=admin_script,
        ),
    )
    if normalized_public_base_url:
        write_file(
            caddy_file,
            build_caddyfile(
                public_base_url=normalized_public_base_url,
                app_host=normalized_app_host,
                app_port=normalized_app_port,
            ),
            mode=0o644,
        )

    if args.enable_linger:
        enable_user_linger(args.linger_user)
    if args.install_crontab:
        install_crontab(cron_file)
    installed_logrotate_path: Path | None = None
    if args.install_logrotate:
        installed_logrotate_path = install_logrotate_config(
            logrotate_file,
            args.logrotate_dir.resolve(),
            args.service_name,
        )
    if args.install_systemd_user:
        install_systemd_user_service(service_file, args.service_name)
    installed_caddy_path: Path | None = None
    if args.install_caddy:
        if not normalized_public_base_url:
            raise SystemExit("--install-caddy requires --public-base-url.")
        installed_caddy_path = install_caddy_config(
            caddy_file,
            args.caddyfile_path.resolve(),
            args.caddy_service_name,
        )
    print("Generated deployment assets:")
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
        *([caddy_file] if normalized_public_base_url else []),
    ]:
        print(f"- {path}")

    print("")
    print("Verification:")
    print(f"- Admin server script: {admin_script}")
    print(f"- Cron file: {cron_file}")
    print(f"- Log file: {log_file}")
    print(f"- Debug log file: {debug_log_path}")
    print(f"- Logrotate config: {logrotate_file}")
    if normalized_public_base_url:
        print(f"- Generated Caddy config: {caddy_file}")
    if installed_logrotate_path is not None:
        print(f"- Installed logrotate config: {installed_logrotate_path}")
    if installed_caddy_path is not None:
        print(f"- Installed Caddy config: {installed_caddy_path}")
    if args.install_systemd_user:
        print("- Admin app service installed and restarted. Check: systemctl --user status "
              f"{args.service_name}")
    else:
        print("- Admin app not started by default. Pass --install-systemd-user to install "
              "and start it.")
    if args.install_caddy:
        print(f"- Caddy config installed and reloaded. Check: systemctl status {args.caddy_service_name}")
    elif normalized_public_base_url:
        print("- Caddy config not installed by default. Pass --install-caddy to install "
              "and reload it.")
    print("- If you passed --install-crontab, check: crontab -l")
    base_url_warning = public_base_url_warning(normalized_public_base_url)
    if base_url_warning:
        print(f"- {base_url_warning}")
    if normalized_public_base_url and normalized_app_host != args.app_host:
        print(
            "- App bind host normalized for reverse proxy use: "
            f"{args.app_host} -> {normalized_app_host}"
        )
    if normalized_public_base_url and normalized_app_port != args.app_port:
        print(
            "- App bind port normalized for reverse proxy use: "
            f"{args.app_port} -> {normalized_app_port}"
        )


if __name__ == "__main__":
    main()
