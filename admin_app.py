import datetime as dt
import base64
from email.utils import parseaddr
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

from flask import Flask, abort, make_response, redirect, render_template, request, url_for
import yaml

from curator import config as config_module
from curator.debug_logs import (
    DEBUG_LOG_TOKEN_HEADER,
    configured_debug_log_path,
    configured_debug_log_token,
    iter_debug_log_files,
    parse_debug_log_line_count,
    read_debug_log_tail,
    validate_configured_debug_log_path,
)
from curator.gmail import normalize_gmail_source_name
from curator.mcp_server import (
    MCP_PROTOCOL_VERSION,
    build_jsonrpc_error,
    handle_request,
    supports_http_protocol_version,
)
from curator.repository import SQLiteRepository
from curator.telemetry import strip_tracking_pixel

CONFIG_PATH = config_module.DEFAULT_CONFIG_PATH
DEFAULT_CONFIG = config_module.DEFAULT_CONFIG


app = Flask(__name__)
ADMIN_TOKEN_COOKIE = "curator_admin_token"
SUBSCRIBER_SESSION_COOKIE = "curator_subscriber_session"
SUBSCRIBER_LOGIN_TOKEN_TTL_MINUTES = 20
SUBSCRIBER_SESSION_TTL_DAYS = 30
TRACKING_PIXEL_GIF = base64.b64decode("R0lGODlhAQABAPAAAAAAAAAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==")
MCP_ENDPOINT_PATH = "/mcp"
MCP_TOKEN_HEADER = "X-MCP-Token"
DEBUG_LOG_ENDPOINT_PATH = "/debug/logs"


def load_config_file() -> dict:
    path = Path(CONFIG_PATH)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_merged_config() -> dict:
    return config_module.merge_dicts(DEFAULT_CONFIG, load_config_file())


def merge_dicts(base: dict, override: dict) -> dict:
    return config_module.merge_dicts(base, override)


def current_newsletter_date() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


def preview_generation_enabled() -> bool:
    return parse_bool(os.getenv("CURATOR_ADMIN_ENABLE_PREVIEW", ""))


def rerender_stored_newsletters_enabled() -> bool:
    return parse_bool(os.getenv("CURATOR_ADMIN_RERENDER_STORED_NEWSLETTERS", ""))


def assess_readiness(config: dict, repository) -> dict:
    from curator.jobs import assess_delivery_readiness

    return assess_delivery_readiness(config, repository)


def run_preview_job(config: dict) -> dict:
    from main import preview_job

    return preview_job(config)


def load_repository(config: dict):
    try:
        database_cfg = config.get("database", {})
        database_path = database_cfg.get("path", "data/newsletter_curator.sqlite3")
        if not Path(database_path).is_absolute():
            database_path = config_module.BASE_DIR / database_path
        repository = SQLiteRepository(Path(database_path))
        allow_schema_reset = bool(database_cfg.get("allow_schema_reset", False)) or str(
            os.getenv("CURATOR_ALLOW_SCHEMA_RESET", "")
        ).strip().lower() in {"1", "true", "yes", "on"}
        repository.initialize(allow_schema_reset=allow_schema_reset)
        return repository
    except Exception:
        return None


def resolve_path_from_config(value: str) -> Path:
    path = Path(str(value or "").strip())
    if not path.is_absolute():
        path = config_module.BASE_DIR / path
    return path


def normalize_story_source_name(story: dict) -> dict:
    normalized = dict(story)
    if str(normalized.get("source_type", "")).strip() == "gmail":
        normalized["source_name"] = normalize_gmail_source_name(str(normalized.get("source_name", "")))
    return normalized


def build_preview_payload(newsletter: dict | None, *, preview_template: str = "market_tape") -> dict | None:
    if not newsletter:
        return None
    content = newsletter.get("content", {}) or {}
    metadata = newsletter.get("metadata", {}) or {}
    render_groups = content.get("render_groups") or metadata.get("render_groups", {})
    stored_body = str(newsletter.get("body", "") or "")
    stored_html = str(newsletter.get("html_body", "") or "")
    plain_body = stored_body
    market_tape_html = stored_html
    email_safe_html = stored_html
    # Stored render_groups are the canonical cached content when they exist.
    if render_groups:
        from curator.rendering import (
            render_digest_html,
            render_digest_text,
            render_email_safe_digest_html,
        )

        plain_body = render_digest_text(render_groups)
        market_tape_html = render_digest_html(render_groups)
        email_safe_html = render_email_safe_digest_html(render_groups)
    elif rerender_stored_newsletters_enabled():
        market_tape_html = stored_html
        email_safe_html = stored_html
    html_body = email_safe_html if preview_template == "email_safe" else market_tape_html
    return {
        "subject": str(newsletter.get("subject", "") or ""),
        "body": plain_body,
        "html_body": strip_tracking_pixel(html_body) if html_body else "",
        "market_tape_html": strip_tracking_pixel(market_tape_html) if market_tape_html else "",
        "email_safe_html": strip_tracking_pixel(email_safe_html) if email_safe_html else "",
    }


def resolve_preview_template() -> str:
    template_name = request.args.get("template", "").strip().lower()
    if template_name == "email_safe":
        return "email_safe"
    if template_name == "gmail_lab":
        return "gmail_lab"
    return "market_tape"


def start_preview_generation(config: dict, newsletter_date: str, generation_token: str) -> None:
    def runner() -> None:
        repository = load_repository(config)
        if repository is None:
            return
        try:
            result = run_preview_job(config)
            preview = result.get("preview")
            if preview is None:
                repository.complete_preview_generation(
                    newsletter_date,
                    generation_token,
                    status="failed",
                    last_error="Preview generation completed but did not produce a digest.",
                )
                return
            repository.complete_preview_generation(
                newsletter_date,
                generation_token,
                status="completed",
            )
        except Exception as exc:
            repository.complete_preview_generation(
                newsletter_date,
                generation_token,
                status="failed",
                last_error=str(exc),
            )

    threading.Thread(target=runner, daemon=True).start()


def get_provided_admin_token() -> str:
    return (
        request.headers.get("X-Admin-Token", "").strip()
        or request.cookies.get(ADMIN_TOKEN_COOKIE, "").strip()
    )


def get_provided_mcp_token() -> str:
    authorization = request.headers.get("Authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return (
        request.headers.get(MCP_TOKEN_HEADER, "").strip()
        or request.headers.get("X-Admin-Token", "").strip()
    )


def get_provided_debug_log_token() -> str:
    authorization = request.headers.get("Authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.headers.get(DEBUG_LOG_TOKEN_HEADER, "").strip()


def normalize_email_address(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    _, parsed = parseaddr(raw)
    parsed = parsed.strip().lower()
    if parsed != raw or "@" not in parsed:
        return ""
    return parsed


def subscriber_login_link_exposure_enabled() -> bool:
    return app.testing or parse_bool(os.getenv("CURATOR_EXPOSE_LOGIN_LINKS", ""))


def subscriber_cookie_secure() -> bool:
    return bool(request.is_secure)


def set_subscriber_session_cookie(response, session_token: str) -> None:
    response.set_cookie(
        SUBSCRIBER_SESSION_COOKIE,
        session_token,
        httponly=True,
        samesite="Lax",
        secure=subscriber_cookie_secure(),
        path="/",
    )


def clear_subscriber_session_cookie(response) -> None:
    response.set_cookie(
        SUBSCRIBER_SESSION_COOKIE,
        "",
        expires=0,
        max_age=0,
        httponly=True,
        samesite="Lax",
        secure=subscriber_cookie_secure(),
        path="/",
    )


def admin_token_configured() -> bool:
    return bool(os.getenv("CURATOR_ADMIN_TOKEN", "").strip())


def admin_cookie_secure() -> bool:
    return bool(request.is_secure)


def set_admin_session_cookie(response, admin_token: str) -> None:
    response.set_cookie(
        ADMIN_TOKEN_COOKIE,
        admin_token,
        httponly=True,
        samesite="Lax",
        secure=admin_cookie_secure(),
        path="/",
    )


def clear_admin_session_cookie(response) -> None:
    response.set_cookie(
        ADMIN_TOKEN_COOKIE,
        "",
        expires=0,
        max_age=0,
        httponly=True,
        samesite="Lax",
        secure=admin_cookie_secure(),
        path="/",
    )


def subscriber_public_base_url() -> str:
    configured = str(os.getenv("CURATOR_PUBLIC_BASE_URL", "")).strip()
    if configured:
        return configured.rstrip("/")
    return request.url_root.rstrip("/")


def build_subscriber_login_confirm_url(raw_token: str) -> str:
    return f"{subscriber_public_base_url()}{url_for('confirm_subscriber_login', token=raw_token)}"


def send_subscriber_login_email(config: dict, to_address: str, confirm_url: str) -> dict:
    from curator.gmail import get_gmail_service, send_email

    credentials_path = resolve_path_from_config(config.get("paths", {}).get("credentials", ""))
    token_path = resolve_path_from_config(config.get("paths", {}).get("token", ""))
    if not credentials_path.exists() or not token_path.exists():
        return {"sent": False, "error": "gmail_credentials_unavailable"}
    subject = "Your Newsletter Curator sign-in link"
    body = (
        "Use this secure sign-in link to access your Newsletter Curator account:\n\n"
        f"{confirm_url}\n\n"
        f"This link expires in {SUBSCRIBER_LOGIN_TOKEN_TTL_MINUTES} minutes. "
        "If you did not request it, you can ignore this email."
    )
    html_body = (
        "<html><body>"
        "<p>Use this secure sign-in link to access your Newsletter Curator account:</p>"
        f'<p><a href="{confirm_url}">{confirm_url}</a></p>'
        f"<p>This link expires in {SUBSCRIBER_LOGIN_TOKEN_TTL_MINUTES} minutes. "
        "If you did not request it, you can ignore this email.</p>"
        "</body></html>"
    )
    try:
        service = get_gmail_service(
            {
                "credentials": str(credentials_path),
                "token": str(token_path),
            }
        )
        send_email(service, to_address, subject, body, html_body)
    except Exception as exc:
        return {"sent": False, "error": str(exc)}
    return {"sent": True, "error": ""}


def get_current_subscriber(repository) -> dict | None:
    if repository is None:
        return None
    session_token = request.cookies.get(SUBSCRIBER_SESSION_COOKIE, "").strip()
    if not session_token:
        return None
    return repository.get_subscriber_by_session_token(session_token)


def require_admin_token() -> str:
    expected = os.getenv("CURATOR_ADMIN_TOKEN", "").strip()
    if not expected:
        return ""
    provided = get_provided_admin_token()
    if provided != expected:
        abort(401)
    return provided


def configured_mcp_token() -> str:
    return (
        os.getenv("CURATOR_MCP_TOKEN", "").strip()
        or os.getenv("CURATOR_ADMIN_TOKEN", "").strip()
    )


def _normalize_origin(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def allowed_mcp_origins() -> set[str]:
    configured = str(os.getenv("CURATOR_MCP_ALLOWED_ORIGINS", "")).strip()
    if configured:
        origins = {
            _normalize_origin(candidate)
            for candidate in configured.split(",")
            if _normalize_origin(candidate)
        }
        return origins
    origins = {
        origin
        for origin in {
            _normalize_origin(os.getenv("CURATOR_PUBLIC_BASE_URL", "")),
            _normalize_origin(request.url_root),
        }
        if origin
    }
    return origins


def mcp_origin_allowed() -> bool:
    origin = request.headers.get("Origin", "").strip()
    if not origin:
        return True
    normalized_origin = _normalize_origin(origin)
    return bool(normalized_origin) and normalized_origin in allowed_mcp_origins()


def make_mcp_json_response(payload: dict, *, status: int = 200):
    response = make_response(json.dumps(payload, separators=(",", ":")), status)
    response.headers["Content-Type"] = "application/json"
    response.headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
    return response


def make_mcp_http_error(status: int, code: int, message: str):
    return make_mcp_json_response(build_jsonrpc_error(code, message, message_id=None), status=status)


def validate_mcp_http_request():
    protocol_version = request.headers.get("MCP-Protocol-Version")
    if not supports_http_protocol_version(protocol_version):
        return make_mcp_http_error(
            400,
            -32600,
            f"Unsupported MCP-Protocol-Version: {protocol_version}",
        )
    if not mcp_origin_allowed():
        return make_mcp_http_error(403, -32600, "Forbidden origin.")
    expected_token = configured_mcp_token()
    if not expected_token:
        if app.testing:
            return None
        return make_mcp_http_error(
            503,
            -32603,
            "CURATOR_MCP_TOKEN or CURATOR_ADMIN_TOKEN must be configured for /mcp.",
        )
    provided_token = get_provided_mcp_token()
    if provided_token != expected_token:
        return make_mcp_http_error(401, -32600, "Unauthorized.")
    return None


def render_admin_template(template_name: str, **context):
    return render_template(
        template_name,
        admin_auth_active=admin_token_configured(),
        **context,
    )


def is_safe_local_redirect_target(target: str) -> bool:
    candidate = str(target or "").strip()
    if not candidate.startswith("/"):
        return False
    parsed = urlsplit(candidate)
    return not parsed.scheme and not parsed.netloc


def resolve_admin_redirect_target() -> str:
    requested = (
        request.args.get("next", "").strip()
        or request.form.get("next", "").strip()
    )
    if is_safe_local_redirect_target(requested) and requested not in {
        url_for("admin_login"),
        url_for("admin_logout"),
    }:
        return requested
    return url_for("config_editor")


def current_request_target() -> str:
    return request.full_path[:-1] if request.full_path.endswith("?") else request.full_path


def require_admin_browser_auth():
    expected = os.getenv("CURATOR_ADMIN_TOKEN", "").strip()
    if not expected:
        return "", None

    header_token = request.headers.get("X-Admin-Token", "").strip()
    if header_token:
        if header_token != expected:
            abort(401)
        return header_token, None

    cookie_token = request.cookies.get(ADMIN_TOKEN_COOKIE, "").strip()
    if cookie_token == expected:
        return cookie_token, None

    response = redirect(url_for("admin_login", next=current_request_target()))
    clear_admin_session_cookie(response)
    return "", response


def parse_bool(value: str | None) -> bool:
    return str(value or "").lower() in {"1", "true", "yes", "on"}


def parse_int(name: str, value: str, min_value: int = 0) -> int:
    parsed = int(value)
    if parsed < min_value:
        raise ValueError(f"{name} must be >= {min_value}")
    return parsed


def render_subscriber_login_page(
    *,
    email_address: str = "",
    message: str = "",
    errors: list[str] | None = None,
    login_link: str = "",
    login_delivery_status: str = "",
    status_code: int = 200,
):
    response = make_response(
        render_template(
            "subscriber_login.html",
            email_address=email_address,
            message=message,
            errors=errors or [],
            login_link=login_link,
            login_delivery_status=login_delivery_status,
        ),
        status_code,
    )
    return response


def require_subscriber_session(repository):
    subscriber = get_current_subscriber(repository)
    if subscriber is not None:
        return subscriber, None
    response = redirect(url_for("subscriber_login"))
    clear_subscriber_session_cookie(response)
    return None, response


def build_subscriber_settings_sources(available_sources: list[dict], selected_sources: list[str]) -> list[dict]:
    selected_lookup = {str(source).strip().lower() for source in selected_sources if str(source).strip()}
    normalized_sources: list[dict] = []
    for source in available_sources:
        source_name = str(source.get("source_name", "")).strip()
        normalized_sources.append(
            {
                "id": int(source.get("id", 0) or 0),
                "source_name": source_name,
                "enabled": bool(source.get("enabled", True)),
                "selected": source_name.lower() in selected_lookup,
            }
        )
    return sorted(
        normalized_sources,
        key=lambda source: (
            0 if source["selected"] else 1,
            0 if source["enabled"] else 1,
            source["source_name"].lower(),
        ),
    )


def normalize_subscriber_preferred_sources(
    form,
    *,
    available_sources: list[dict],
    current_profile: dict,
) -> list[str]:
    from curator.jobs import normalize_preferred_sources

    selected_sources = normalize_preferred_sources(form.getlist("preferred_source"))
    source_by_lower = {
        str(source.get("source_name", "")).strip().lower(): str(source.get("source_name", "")).strip()
        for source in available_sources
        if str(source.get("source_name", "")).strip()
    }
    enabled_sources = {
        str(source.get("source_name", "")).strip().lower(): str(source.get("source_name", "")).strip()
        for source in available_sources
        if str(source.get("source_name", "")).strip() and bool(source.get("enabled", True))
    }
    normalized: list[str] = []
    seen: set[str] = set()

    for raw_source in selected_sources:
        lowered = raw_source.lower()
        canonical = enabled_sources.get(lowered) or source_by_lower.get(lowered)
        if not canonical or canonical.lower() in seen:
            continue
        normalized.append(canonical)
        seen.add(canonical.lower())

    for raw_source in current_profile.get("preferred_sources", []):
        lowered = str(raw_source).strip().lower()
        if not lowered or lowered in seen:
            continue
        canonical = source_by_lower.get(lowered, str(raw_source).strip())
        source_row = next(
            (source for source in available_sources if str(source.get("source_name", "")).strip().lower() == lowered),
            None,
        )
        if source_row is not None and not bool(source_row.get("enabled", True)):
            normalized.append(canonical)
            seen.add(lowered)
    return normalized


def render_subscriber_settings_page(
    *,
    subscriber: dict,
    profile: dict,
    available_sources: list[dict],
    message: str = "",
    errors: list[str] | None = None,
    status_code: int = 200,
):
    return make_response(
        render_template(
            "subscriber_settings.html",
            subscriber=subscriber,
            profile=profile,
            available_sources=available_sources,
            message=message,
            errors=errors or [],
        ),
        status_code,
    )


def update_config_from_form(raw_config: dict, form) -> tuple[dict, list[str]]:
    errors: list[str] = []
    updated = dict(raw_config)

    def ensure(path: list[str]) -> dict:
        cursor = updated
        for key in path:
            if not isinstance(cursor.get(key), dict):
                cursor[key] = {}
            cursor = cursor[key]
        return cursor

    try:
        ensure(["gmail"])["label"] = form.get("gmail_label", "").strip() or DEFAULT_CONFIG["gmail"]["label"]
        ensure(["gmail"])["query_time_window"] = (
            form.get("gmail_query_time_window", "").strip()
            or DEFAULT_CONFIG["gmail"]["query_time_window"]
        )

        ensure(["openai"])["reasoning_model"] = (
            form.get("openai_reasoning_model", "").strip()
            or DEFAULT_CONFIG["openai"]["reasoning_model"]
        )
        ensure(["openai"])["summary_model"] = (
            form.get("openai_summary_model", "").strip()
            or DEFAULT_CONFIG["openai"]["summary_model"]
        )
        ensure(["persona"])["text"] = form.get("persona_text", "").strip()

        additional_sources = ensure(["additional_sources"])
        additional_sources["enabled"] = parse_bool(form.get("additional_enabled"))
        additional_sources["script_path"] = (
            form.get("additional_script_path", "").strip()
            or DEFAULT_CONFIG["additional_sources"]["script_path"]
        )
        additional_sources["feeds_file"] = form.get("additional_feeds_file", "").strip()
        additional_sources["hours"] = parse_int(
            "additional_sources.hours", form.get("additional_hours", "24"), 1
        )
        additional_sources["top_per_category"] = parse_int(
            "additional_sources.top_per_category",
            form.get("additional_top_per_category", "5"),
            1,
        )
        additional_sources["max_total"] = parse_int(
            "additional_sources.max_total", form.get("additional_max_total", "20"), 1
        )

        limits = ensure(["limits"])
        limits["max_links_per_email"] = parse_int(
            "limits.max_links_per_email", form.get("limit_max_links_per_email", "15"), 1
        )
        limits["select_top_stories"] = parse_int(
            "limits.select_top_stories", form.get("limit_select_top_stories", "20"), 1
        )
        limits["max_per_category"] = parse_int(
            "limits.max_per_category", form.get("limit_max_per_category", "3"), 1
        )
        limits["final_top_stories"] = parse_int(
            "limits.final_top_stories", form.get("limit_final_top_stories", "15"), 1
        )
        limits["max_article_chars"] = parse_int(
            "limits.max_article_chars", form.get("limit_max_article_chars", "6000"), 500
        )
        limits["max_summary_workers"] = parse_int(
            "limits.max_summary_workers", form.get("limit_max_summary_workers", "5"), 1
        )
        limits["source_quotas"] = {
            "gmail": parse_int("limits.source_quotas.gmail", form.get("quota_gmail", "10"), 0),
            "additional_source": parse_int(
                "limits.source_quotas.additional_source",
                form.get("quota_additional_source", "5"),
                0,
            ),
        }

        quota_total = (
            limits["source_quotas"]["gmail"] + limits["source_quotas"]["additional_source"]
        )
        if quota_total != limits["final_top_stories"]:
            errors.append(
                "limits.final_top_stories must equal quota_gmail + quota_additional_source."
            )

        email_cfg = ensure(["email"])
        recipients_raw = form.get("email_digest_recipients", "").strip()
        recipients = [line.strip() for line in recipients_raw.splitlines() if line.strip()]
        email_cfg["digest_recipients"] = recipients
        email_cfg["digest_subject"] = (
            form.get("email_digest_subject", "").strip()
            or DEFAULT_CONFIG["email"]["digest_subject"]
        )
        email_cfg["alert_recipient"] = (
            form.get("email_alert_recipient", "").strip()
            or DEFAULT_CONFIG["email"]["alert_recipient"]
        )
        email_cfg["alert_subject_prefix"] = (
            form.get("email_alert_subject_prefix", "").strip()
            or DEFAULT_CONFIG["email"]["alert_subject_prefix"]
        )
    except ValueError as exc:
        errors.append(str(exc))

    return updated, errors


def backup_config(path: Path) -> None:
    if not path.exists():
        return
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M%S")
    backup = path.with_suffix(path.suffix + f".{timestamp}.bak")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def update_source_selections(repository, form) -> None:
    if repository is None:
        return
    for source in repository.list_sources_with_selection():
        field_name = f"source_enabled_{source['id']}"
        repository.set_source_selection_by_id(
            int(source["id"]),
            enabled=parse_bool(form.get(field_name)),
        )


@app.route("/health", methods=["GET"])
def health():
    return {"ok": True}


@app.route(DEBUG_LOG_ENDPOINT_PATH, methods=["GET"])
def debug_logs():
    expected_token = configured_debug_log_token()
    if not expected_token:
        return {"error": "Debug log endpoint is not configured."}, 503

    provided_token = get_provided_debug_log_token()
    if provided_token != expected_token:
        return {"error": "Unauthorized."}, 401

    try:
        requested_lines = parse_debug_log_line_count(request.args.get("lines"))
    except ValueError as exc:
        return {"error": str(exc)}, 400
    merged = parse_bool(request.args.get("merged"))

    path, path_status = validate_configured_debug_log_path(configured_debug_log_path())
    if path is None:
        if path_status == "missing":
            return {"error": "Debug log endpoint is not configured."}, 503
        return {"error": "Debug log path is invalid."}, 503
    if not path.exists() and not any(candidate.exists() for candidate in iter_debug_log_files(path, merged=True)):
        return {"error": "Debug log file was not found."}, 404

    try:
        lines, truncated, source_paths = read_debug_log_tail(
            path,
            lines=requested_lines,
            merged=merged,
        )
    except OSError:
        return {"error": "Debug log file could not be read."}, 503

    return {
        "path": str(path),
        "merged": merged,
        "source_paths": source_paths,
        "line_count": len(lines),
        "truncated": truncated,
        "lines": lines,
    }


@app.route(MCP_ENDPOINT_PATH, methods=["GET", "POST", "DELETE"])
def remote_mcp():
    error_response = validate_mcp_http_request()
    if error_response is not None:
        return error_response

    if request.method == "GET":
        return ("", 405)

    if request.method == "DELETE":
        return ("", 405)

    try:
        message = request.get_json(force=True)
    except Exception:
        return make_mcp_http_error(400, -32700, "Invalid JSON body.")

    if not isinstance(message, dict):
        return make_mcp_http_error(400, -32600, "Expected a single JSON-RPC object.")

    method = message.get("method")
    if not method:
        return ("", 202)

    response_payload = handle_request(message, config_path=CONFIG_PATH)
    if response_payload is None:
        return ("", 202)
    return make_mcp_json_response(response_payload, status=200)


@app.errorhandler(401)
def unauthorized(_):
    return (
        "Unauthorized. Provide CURATOR_ADMIN_TOKEN via header 'X-Admin-Token' "
        "or sign in at /admin/login.",
        401,
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not admin_token_configured():
        return redirect(url_for("config_editor"))

    expected = os.getenv("CURATOR_ADMIN_TOKEN", "").strip()
    if request.cookies.get(ADMIN_TOKEN_COOKIE, "").strip() == expected and request.method == "GET":
        return redirect(resolve_admin_redirect_target())

    message = ""
    errors: list[str] = []
    if request.method == "POST":
        posted_token = request.form.get("admin_token", "").strip()
        if not posted_token:
            errors.append("Enter the admin token.")
        elif posted_token != expected:
            errors.append("The admin token is invalid.")
        else:
            response = redirect(resolve_admin_redirect_target())
            set_admin_session_cookie(response, posted_token)
            return response

    if request.args.get("logged_out", "").strip() == "1" and not errors:
        message = "You have been signed out."
    return make_response(
        render_admin_template(
            "admin_login.html",
            message=message,
            errors=errors,
            next_target=resolve_admin_redirect_target(),
        )
    )


@app.route("/admin/logout", methods=["GET", "POST"])
def admin_logout():
    response = redirect(url_for("admin_login", logged_out="1"))
    clear_admin_session_cookie(response)
    return response


@app.route("/login", methods=["GET", "POST"])
def subscriber_login():
    merged = load_merged_config()
    repository = load_repository(merged)
    current_subscriber = get_current_subscriber(repository)
    if current_subscriber is not None and request.method == "GET":
        return redirect(url_for("subscriber_account"))

    message = ""
    errors: list[str] = []
    login_link = ""
    login_delivery_status = ""
    email_address = ""

    if request.method == "POST":
        email_address = normalize_email_address(request.form.get("email_address", ""))
        if not email_address:
            errors.append("Enter a valid email address.")
        elif repository is None:
            errors.append("Subscriber login is unavailable because the repository could not be opened.")
        else:
            subscriber = repository.upsert_subscriber(email_address)
            token_payload = repository.create_subscriber_login_token(
                int(subscriber["id"]),
                ttl_minutes=SUBSCRIBER_LOGIN_TOKEN_TTL_MINUTES,
                request_ip=_request_ip(),
                user_agent=request.headers.get("User-Agent", ""),
            )
            login_link = build_subscriber_login_confirm_url(token_payload["token"])
            delivery = send_subscriber_login_email(merged, email_address, login_link)
            login_delivery_status = "sent" if delivery.get("sent") else "fallback"
            if delivery.get("sent"):
                message = f"Sign-in link sent to {email_address}."
                if not subscriber_login_link_exposure_enabled():
                    login_link = ""
            elif subscriber_login_link_exposure_enabled():
                message = (
                    "Email delivery is unavailable on this server right now. "
                    "Use the temporary sign-in link below."
                )
            else:
                errors.append("Sign-in email delivery is unavailable right now. Contact the operator.")
                login_link = ""
                login_delivery_status = "failed"

    if request.args.get("logged_out", "").strip() == "1" and not (message or errors):
        message = "You have been signed out."
    return render_subscriber_login_page(
        email_address=email_address,
        message=message,
        errors=errors,
        login_link=login_link if subscriber_login_link_exposure_enabled() else "",
        login_delivery_status=login_delivery_status,
    )


@app.route("/login/confirm", methods=["GET"])
def confirm_subscriber_login():
    merged = load_merged_config()
    repository = load_repository(merged)
    if repository is None:
        return render_subscriber_login_page(
            errors=["Subscriber login is unavailable because the repository could not be opened."],
            status_code=503,
        )

    raw_token = request.args.get("token", "").strip()
    subscriber = repository.consume_subscriber_login_token(raw_token)
    if subscriber is None:
        return render_subscriber_login_page(
            errors=["This sign-in link is invalid or has expired."],
            status_code=400,
        )

    session_payload = repository.create_subscriber_session(
        int(subscriber["id"]),
        ttl_days=SUBSCRIBER_SESSION_TTL_DAYS,
        ip_address=_request_ip(),
        user_agent=request.headers.get("User-Agent", ""),
    )
    response = redirect(url_for("subscriber_account"))
    set_subscriber_session_cookie(response, session_payload["token"])
    return response


@app.route("/account", methods=["GET"])
def subscriber_account():
    merged = load_merged_config()
    repository = load_repository(merged)
    subscriber, redirect_response = require_subscriber_session(repository)
    if redirect_response is not None:
        return redirect_response
    return make_response(
        render_template(
            "subscriber_account.html",
            subscriber=subscriber,
        )
    )


@app.route("/settings", methods=["GET", "POST"])
def subscriber_settings():
    merged = load_merged_config()
    repository = load_repository(merged)
    subscriber, redirect_response = require_subscriber_session(repository)
    if redirect_response is not None:
        return redirect_response

    available_sources = repository.list_sources_with_selection() if repository else []
    profile = repository.get_subscriber_profile(int(subscriber["id"])) if repository else {
        "subscriber_id": int(subscriber["id"]),
        "persona_text": "",
        "preferred_sources": [],
        "created_at": "",
        "updated_at": "",
    }
    errors: list[str] = []
    message = ""

    if request.method == "POST":
        persona_text = str(request.form.get("persona_text", "") or "").strip()
        preferred_sources = normalize_subscriber_preferred_sources(
            request.form,
            available_sources=available_sources,
            current_profile=profile,
        )
        profile = repository.upsert_subscriber_profile(
            int(subscriber["id"]),
            persona_text=persona_text,
            preferred_sources=preferred_sources,
        )
        return redirect(url_for("subscriber_settings", saved="1"))

    if request.args.get("saved", "").strip() == "1":
        message = "Subscriber settings saved."

    available_sources = build_subscriber_settings_sources(
        available_sources,
        profile.get("preferred_sources", []),
    )
    return render_subscriber_settings_page(
        subscriber=subscriber,
        profile=profile,
        available_sources=available_sources,
        message=message,
        errors=errors,
    )


@app.route("/logout", methods=["GET", "POST"])
def subscriber_logout():
    merged = load_merged_config()
    repository = load_repository(merged)
    session_token = request.cookies.get(SUBSCRIBER_SESSION_COOKIE, "").strip()
    if repository is not None and session_token:
        repository.revoke_subscriber_session(session_token)
    response = redirect(url_for("subscriber_login", logged_out="1"))
    clear_subscriber_session_cookie(response)
    return response


@app.route("/", methods=["GET", "POST"])
def config_editor():
    _admin_token, redirect_response = require_admin_browser_auth()
    if redirect_response is not None:
        return redirect_response
    raw = load_config_file()
    merged = merge_dicts(DEFAULT_CONFIG, raw)
    repository = load_repository(merged)
    available_sources = repository.list_sources_with_selection() if repository else []
    message = ""
    errors: list[str] = []

    if request.method == "POST":
        updated_raw, errors = update_config_from_form(raw, request.form)
        if not errors:
            updated_merged = merge_dicts(DEFAULT_CONFIG, updated_raw)
            path = Path(CONFIG_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            backup_config(path)
            with path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(updated_raw, handle, sort_keys=False)
            repository = load_repository(updated_merged)
            update_source_selections(repository, request.form)
            return redirect(url_for("config_editor", saved="1"))
        merged = merge_dicts(DEFAULT_CONFIG, updated_raw)
        repository = load_repository(merged)
        available_sources = repository.list_sources_with_selection() if repository else []

    if request.args.get("saved") == "1":
        message = f"Saved {CONFIG_PATH} successfully."

    response = make_response(
        render_admin_template(
            "admin_config.html",
            config=merged,
            config_path=CONFIG_PATH,
            available_sources=available_sources,
            message=message,
            errors=errors,
        )
    )
    return response


@app.route("/preview", methods=["GET"])
def preview_newsletter():
    _admin_token, redirect_response = require_admin_browser_auth()
    if redirect_response is not None:
        return redirect_response
    preview_template = resolve_preview_template()
    merged = load_merged_config()
    repository = load_repository(merged)
    error = ""
    preview = None
    result = None
    status_code = 200
    generation_in_progress = False
    generation_state = None
    generation_started = False

    newsletter_date = current_newsletter_date()
    if repository is None:
        error = "Repository is unavailable. Check the server logs for configuration or schema issues."
        status_code = 200
    else:
        cached_newsletter = repository.get_daily_newsletter(newsletter_date)
        if cached_newsletter is not None:
            preview = build_preview_payload(cached_newsletter, preview_template=preview_template)
            metadata = cached_newsletter.get("metadata", {})
            result = {
                "status": "completed",
                "ranked_candidates": int(metadata.get("ranked_candidates", 0) or 0),
                "selected": int(metadata.get("selected", 0) or 0),
                "accepted_items": len(cached_newsletter.get("selected_items", []) or []),
                "cached_preview": True,
            }
        elif not preview_generation_enabled():
            error = (
                "Live preview generation is disabled in lightweight debug mode. "
                "Set CURATOR_ADMIN_ENABLE_PREVIEW=1 to enable it."
            )
            status_code = 200
        else:
            readiness = assess_readiness(merged, repository)
            if not readiness["ok"]:
                required_source_types = readiness.get("required_source_types", [])
                if required_source_types:
                    source_hint = ", ".join(required_source_types)
                    error = (
                        "No delivery-ready stories are available yet. "
                        f"Run the fetch job to populate the repository for: {source_hint}."
                    )
                else:
                    error = "No delivery-ready stories are available yet. Run the fetch job and try again."
                status_code = 200
            else:
                lock_state = repository.acquire_preview_generation(newsletter_date)
                if not lock_state.get("acquired", True):
                    generation_in_progress = True
                    generation_state = lock_state
                    status_code = 202
                else:
                    generation_token = str(lock_state.get("generation_token", ""))
                    if generation_token:
                        start_preview_generation(merged, newsletter_date, generation_token)
                    generation_in_progress = True
                    generation_state = lock_state
                    generation_started = True
                    status_code = 202

    if generation_in_progress and repository:
        cached_newsletter = repository.get_daily_newsletter(newsletter_date)
        if cached_newsletter is not None:
            preview = build_preview_payload(cached_newsletter, preview_template=preview_template)
            metadata = cached_newsletter.get("metadata", {})
            result = {
                "status": "completed",
                "ranked_candidates": int(metadata.get("ranked_candidates", 0) or 0),
                "selected": int(metadata.get("selected", 0) or 0),
                "accepted_items": len(cached_newsletter.get("selected_items", []) or []),
                "cached_preview": True,
            }
            generation_in_progress = False
            generation_state = None
            generation_started = False
            status_code = 200
        elif generation_state and generation_state.get("status") == "failed":
            error = str(generation_state.get("last_error", "") or "Preview generation failed.")
            generation_in_progress = False
            status_code = 200

    response = make_response(
        render_admin_template(
            "digest_preview.html",
            config_path=CONFIG_PATH,
            preview=preview,
            result=result,
            error=error,
            generation_in_progress=generation_in_progress,
            generation_state=generation_state,
            generation_started=generation_started,
            preview_template=preview_template,
        ),
        status_code,
    )
    return response


def _request_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.remote_addr or ""


@app.route("/track/open/<open_token>.gif", methods=["GET"])
def track_newsletter_open(open_token: str):
    repository = load_repository(load_merged_config())
    if repository is None:
        abort(404)

    repository.record_newsletter_open(
        open_token,
        user_agent=request.headers.get("User-Agent", ""),
        ip_address=_request_ip(),
    )
    response = make_response(TRACKING_PIXEL_GIF)
    response.headers["Content-Type"] = "image/gif"
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.route("/track/click/<click_token>", methods=["GET"])
def track_newsletter_click(click_token: str):
    repository = load_repository(load_merged_config())
    if repository is None:
        abort(404)

    click = repository.record_newsletter_click(
        click_token,
        user_agent=request.headers.get("User-Agent", ""),
        ip_address=_request_ip(),
    )
    if click is None:
        abort(404)
    return redirect(click["target_url"], code=302)


@app.route("/stories", methods=["GET"])
def story_explorer():
    _admin_token, redirect_response = require_admin_browser_auth()
    if redirect_response is not None:
        return redirect_response
    merged = load_merged_config()
    repository = load_repository(merged)
    source_type = request.args.get("source_type", "").strip() or None
    source_name = request.args.get("source_name", "").strip() or None
    stories = repository.list_stories(source_type=source_type) if repository else []
    if source_name:
        source_name_lower = source_name.lower()
        stories = [
            normalize_story_source_name(story)
            for story in stories
            if source_name_lower in normalize_gmail_source_name(str(story.get("source_name", ""))).lower()
            or source_name_lower in str(story.get("source_name", "")).lower()
        ]
    else:
        stories = [
            normalize_story_source_name(story)
            for story in stories
        ]
    available_sources = repository.list_sources_with_selection() if repository else []
    available_sources = [
        {
            **source,
            "source_name": (
                normalize_gmail_source_name(str(source.get("source_name", "")))
                if str(source.get("source_type", "")).strip() == "gmail"
                else source.get("source_name", "")
            ),
        }
        for source in available_sources
    ]
    response = make_response(
        render_admin_template(
            "story_explorer.html",
            config_path=CONFIG_PATH,
            stories=stories,
            source_type=source_type or "",
            source_name=source_name or "",
            available_sources=available_sources,
        )
    )
    return response


@app.route("/newsletters", methods=["GET"])
def newsletter_history():
    _admin_token, redirect_response = require_admin_browser_auth()
    if redirect_response is not None:
        return redirect_response
    merged = load_merged_config()
    repository = load_repository(merged)
    newsletters = repository.list_daily_newsletters(limit=30) if repository else []
    response = make_response(
        render_admin_template(
            "newsletter_history.html",
            config_path=CONFIG_PATH,
            newsletters=newsletters,
        )
    )
    return response


@app.route("/newsletters/<newsletter_date>", methods=["GET"])
def newsletter_history_detail(newsletter_date: str):
    _admin_token, redirect_response = require_admin_browser_auth()
    if redirect_response is not None:
        return redirect_response
    merged = load_merged_config()
    repository = load_repository(merged)
    newsletter = repository.get_daily_newsletter(newsletter_date) if repository else None
    if newsletter is None:
        abort(404)

    response = make_response(
        render_admin_template(
            "newsletter_history_detail.html",
            config_path=CONFIG_PATH,
            newsletter=newsletter,
            preview=build_preview_payload(newsletter),
        )
    )
    return response


@app.route("/analytics", methods=["GET"])
def analytics_dashboard():
    _admin_token, redirect_response = require_admin_browser_auth()
    if redirect_response is not None:
        return redirect_response
    merged = load_merged_config()
    repository = load_repository(merged)
    recent_newsletters = repository.list_newsletter_analytics(limit=14) if repository else []
    window_stats = repository.get_newsletter_aggregate_stats() if repository else []
    top_clicked_stories = (
        repository.list_top_clicked_stories(trailing_days=30, limit=10) if repository else []
    )
    response = make_response(
        render_admin_template(
            "analytics.html",
            config_path=CONFIG_PATH,
            recent_newsletters=recent_newsletters,
            window_stats=window_stats,
            top_clicked_stories=top_clicked_stories,
        )
    )
    return response


if __name__ == "__main__":
    host = os.getenv("CURATOR_ADMIN_HOST", "127.0.0.1")
    port = int(os.getenv("CURATOR_ADMIN_PORT", "8080"))
    app.run(host=host, port=port, debug=False)
