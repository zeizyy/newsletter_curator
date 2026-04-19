import datetime as dt
import base64
from email.utils import parseaddr
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

from flask import Flask, abort, make_response, redirect, render_template, request, url_for
import requests
from werkzeug.middleware.proxy_fix import ProxyFix
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
from curator.pricing import estimate_openai_text_cost_usd, format_usd_cost
from curator.repository import SQLiteRepository
from curator.telemetry import (
    build_settings_url,
    resolve_public_base_url,
    resolve_tracking_base_url,
    strip_tracking_pixel,
    telemetry_enabled,
)

CONFIG_PATH = config_module.DEFAULT_CONFIG_PATH
DEFAULT_CONFIG = config_module.DEFAULT_CONFIG


app = Flask(__name__)
if str(os.getenv("CURATOR_TRUST_PROXY_HEADERS", "")).strip().lower() in {"1", "true", "yes", "on"}:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

ADMIN_TOKEN_COOKIE = "curator_admin_token"
SUBSCRIBER_SESSION_COOKIE = "curator_subscriber_session"
SUBSCRIBER_LOGIN_TOKEN_TTL_MINUTES = 20
SUBSCRIBER_SESSION_TTL_DAYS = 30
DEFAULT_SUBSCRIBER_SIGNUP_URL = "https://buttondown.com/zeizyynewsletter"
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TRACKING_PIXEL_GIF = base64.b64decode("R0lGODlhAQABAPAAAAAAAAAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==")
MCP_ENDPOINT_PATH = "/mcp"
MCP_TOKEN_HEADER = "X-MCP-Token"
DEBUG_LOG_ENDPOINT_PATH = "/debug/logs"
_SUBSCRIBER_LOGIN_ATTEMPT_LOCK = threading.Lock()
_SUBSCRIBER_LOGIN_ATTEMPTS: dict[str, dict[str, list[float]]] = {
    "ip": {},
    "email": {},
}


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


def open_repository_status(config: dict) -> tuple[SQLiteRepository | None, dict]:
    database_cfg = config.get("database", {})
    database_path = resolve_path_from_config(database_cfg.get("path", "data/newsletter_curator.sqlite3"))
    allow_schema_reset = bool(database_cfg.get("allow_schema_reset", False)) or str(
        os.getenv("CURATOR_ALLOW_SCHEMA_RESET", "")
    ).strip().lower() in {"1", "true", "yes", "on"}
    try:
        repository = SQLiteRepository(database_path)
        repository.initialize(allow_schema_reset=allow_schema_reset)
        with repository.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return repository, {
            "label": "SQLite Connectivity",
            "status": "ok",
            "tone": "success",
            "summary": "Repository opened and responded to a read query.",
            "details": [
                f"database.path={database_path}",
                "SQLite query check: SELECT 1",
            ],
        }
    except Exception as exc:
        return None, {
            "label": "SQLite Connectivity",
            "status": "error",
            "tone": "warning",
            "summary": "Repository could not be opened.",
            "details": [
                f"database.path={database_path}",
                f"error={exc}",
            ],
        }


def _clone_default_config() -> dict:
    return config_module.merge_dicts(DEFAULT_CONFIG, {})


def load_dashboard_config_state() -> tuple[dict, dict]:
    config_path = Path(CONFIG_PATH)
    try:
        merged = load_merged_config()
        return merged, {
            "ok": True,
            "config_path": str(config_path),
            "errors": [],
        }
    except Exception as exc:
        return _clone_default_config(), {
            "ok": False,
            "config_path": str(config_path),
            "errors": [str(exc)],
        }


def _parse_iso_datetime(value: str | None) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_age(value: str | None) -> str:
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return "unknown"
    delta = dt.datetime.now(dt.UTC) - parsed.astimezone(dt.UTC)
    total_seconds = max(0, int(delta.total_seconds()))
    if total_seconds < 60:
        return f"{total_seconds}s ago"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m ago"
    if total_seconds < 86400:
        return f"{total_seconds // 3600}h ago"
    return f"{total_seconds // 86400}d ago"


def _int_config_error(name: str, value, *, minimum: int = 0) -> str | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return f"{name} must be an integer."
    if parsed < minimum:
        return f"{name} must be >= {minimum}."
    return None


def build_config_validity_check(config: dict, config_state: dict) -> dict:
    errors = list(config_state.get("errors", []) or [])
    limits = config.get("limits", {})
    source_quotas = limits.get("source_quotas", {})
    for field_name, raw_value, minimum in [
        ("limits.max_links_per_email", limits.get("max_links_per_email"), 1),
        ("limits.select_top_stories", limits.get("select_top_stories"), 1),
        ("limits.max_per_category", limits.get("max_per_category"), 1),
        ("limits.final_top_stories", limits.get("final_top_stories"), 1),
        ("limits.source_quotas.gmail", source_quotas.get("gmail"), 0),
        ("limits.source_quotas.additional_source", source_quotas.get("additional_source"), 0),
    ]:
        error = _int_config_error(field_name, raw_value, minimum=minimum)
        if error:
            errors.append(error)
    try:
        final_top_stories = int(limits.get("final_top_stories", 0) or 0)
        gmail_quota = int(source_quotas.get("gmail", 0) or 0)
        additional_quota = int(source_quotas.get("additional_source", 0) or 0)
        if final_top_stories != gmail_quota + additional_quota:
            errors.append(
                "limits.final_top_stories must equal limits.source_quotas.gmail + limits.source_quotas.additional_source."
            )
    except (TypeError, ValueError):
        pass
    if not str(config.get("gmail", {}).get("query_time_window", "")).strip():
        errors.append("gmail.query_time_window must not be blank.")
    if not str(config.get("database", {}).get("path", "")).strip():
        errors.append("database.path must not be blank.")
    if not str(config.get("paths", {}).get("credentials", "")).strip():
        errors.append("paths.credentials must not be blank.")
    if not str(config.get("paths", {}).get("token", "")).strip():
        errors.append("paths.token must not be blank.")
    if errors:
        return {
            "label": "Config Validity",
            "status": "error",
            "tone": "warning",
            "summary": "Config is loaded with validation errors.",
            "details": [f"config_path={config_state['config_path']}", *errors],
        }
    return {
        "label": "Config Validity",
        "status": "ok",
        "tone": "success",
        "summary": "Config loaded and passed structural checks.",
        "details": [f"config_path={config_state['config_path']}"],
    }


def build_gmail_auth_presence_check(config: dict) -> dict:
    credentials_path = resolve_path_from_config(config.get("paths", {}).get("credentials", ""))
    token_path = resolve_path_from_config(config.get("paths", {}).get("token", ""))
    details = [
        f"credentials={credentials_path}",
        f"token={token_path}",
    ]
    missing: list[str] = []
    if not credentials_path.exists():
        missing.append("credentials file missing")
    if not token_path.exists():
        missing.append("token file missing")
    if missing:
        return {
            "label": "Gmail Auth Presence",
            "status": "error",
            "tone": "warning",
            "summary": "Gmail auth files are incomplete.",
            "details": [*details, *missing],
        }
    return {
        "label": "Gmail Auth Presence",
        "status": "ok",
        "tone": "success",
        "summary": "Credentials and token files are present.",
        "details": details,
    }


def build_public_base_url_check(config: dict) -> dict:
    tracking_on = telemetry_enabled(config)
    configured_public_base_url = resolve_public_base_url()
    subscriber_base = subscriber_public_base_url()
    details = [
        f"tracking_enabled={tracking_on}",
        f"configured_public_base_url={configured_public_base_url or '(blank)'}",
        f"subscriber_public_base_url={subscriber_base or '(blank)'}",
    ]
    if not tracking_on:
        return {
            "label": "Public Base URL Consistency",
            "status": "info",
            "tone": "info",
            "summary": "Tracking is disabled; public base URL consistency is not required right now.",
            "details": details,
        }
    parsed_public = urlsplit(configured_public_base_url)
    if (
        not configured_public_base_url
        or parsed_public.scheme not in {"http", "https"}
        or not parsed_public.netloc
    ):
        return {
            "label": "Public Base URL Consistency",
            "status": "error",
            "tone": "warning",
            "summary": "Tracking is enabled but the public base URL is not a valid absolute HTTP(S) URL.",
            "details": details,
        }
    if configured_public_base_url.rstrip("/") != subscriber_base.rstrip("/"):
        return {
            "label": "Public Base URL Consistency",
            "status": "error",
            "tone": "warning",
            "summary": "Mismatch between configured public base URL and subscriber public base URL.",
            "details": details,
        }
    return {
        "label": "Public Base URL Consistency",
        "status": "ok",
        "tone": "success",
        "summary": "Tracking links and subscriber links resolve to the same public host.",
        "details": details,
    }


def _query_window_seconds(query: str) -> int:
    normalized = str(query or "").strip().lower()
    if normalized.startswith("newer_than:") and normalized.endswith("d"):
        try:
            return int(normalized.removeprefix("newer_than:")[:-1]) * 86400
        except ValueError:
            return 86400
    if normalized.startswith("newer_than:") and normalized.endswith("h"):
        try:
            return int(normalized.removeprefix("newer_than:")[:-1]) * 3600
        except ValueError:
            return 86400
    return 86400


def _freshness_tone(age_seconds: int, *, threshold_seconds: int) -> tuple[str, str]:
    if age_seconds <= threshold_seconds:
        return "ok", "success"
    if age_seconds <= threshold_seconds * 2:
        return "warning", "info"
    return "error", "warning"


def _run_age_seconds(run: dict | None) -> int | None:
    if not isinstance(run, dict):
        return None
    finished_at = _parse_iso_datetime(run.get("finished_at"))
    if finished_at is None:
        return None
    return max(0, int((dt.datetime.now(dt.UTC) - finished_at.astimezone(dt.UTC)).total_seconds()))


def build_ingest_freshness_check(config: dict, repository) -> dict:
    source_labels = [("gmail", "Gmail")]
    if bool(config.get("additional_sources", {}).get("enabled", False)):
        source_labels.append(("additional_source", "Additional Sources"))
    details: list[str] = []
    overall_status = "ok"
    overall_tone = "success"
    for source_type, label in source_labels:
        latest_completed = repository.get_latest_ingestion_run(source_type, status="completed") if repository else None
        latest_any = repository.get_latest_ingestion_run(source_type) if repository else None
        threshold_seconds = (
            _query_window_seconds(config.get("gmail", {}).get("query_time_window", "newer_than:1d"))
            if source_type == "gmail"
            else max(1, int(config.get("additional_sources", {}).get("hours", 24) or 24)) * 3600
        )
        if latest_completed is None:
            overall_status = "error"
            overall_tone = "warning"
            latest_status = str((latest_any or {}).get("status", "")).strip() or "none"
            details.append(f"{label}: no successful ingest run yet (latest status={latest_status})")
            continue
        age_seconds = _run_age_seconds(latest_completed) or 0
        status, tone = _freshness_tone(age_seconds, threshold_seconds=threshold_seconds)
        if status == "error":
            overall_status = "error"
            overall_tone = "warning"
        elif status == "warning" and overall_status == "ok":
            overall_status = "warning"
            overall_tone = "info"
        details.append(
            (
                f"{label}: last completed run #{latest_completed['id']} "
                f"finished { _format_age(latest_completed.get('finished_at')) } "
                f"(threshold {max(1, threshold_seconds // 3600)}h)"
            )
        )
        if latest_any and latest_any["id"] != latest_completed["id"]:
            details.append(f"{label}: latest run status={latest_any['status']}")
    summary = "All required ingest pipelines have recent successful runs."
    if overall_status == "warning":
        summary = "At least one successful ingest run is getting stale."
    elif overall_status == "error":
        summary = "At least one ingest pipeline is missing a recent successful run."
    return {
        "label": "Last Successful Ingest",
        "status": overall_status,
        "tone": overall_tone,
        "summary": summary,
        "details": details or ["No ingest sources are enabled."],
    }


def build_delivery_freshness_check(repository) -> dict:
    recent_runs = repository.list_recent_delivery_runs(limit=10) if repository else []
    latest_completed = next(
        (run for run in recent_runs if str(run.get("status", "")).strip() == "completed"),
        None,
    )
    if latest_completed is None:
        latest_status = str(recent_runs[0].get("status", "")).strip() if recent_runs else "none"
        return {
            "label": "Last Successful Delivery",
            "status": "error",
            "tone": "warning",
            "summary": "No successful delivery run is available.",
            "details": [f"latest_delivery_status={latest_status}"],
        }
    age_seconds = _run_age_seconds(latest_completed) or 0
    status, tone = _freshness_tone(age_seconds, threshold_seconds=36 * 3600)
    metadata = latest_completed.get("metadata", {}) or {}
    summary = "Latest successful delivery is recent."
    if status == "warning":
        summary = "Latest successful delivery is older than expected."
    elif status == "error":
        summary = "Latest successful delivery is stale."
    return {
        "label": "Last Successful Delivery",
        "status": status,
        "tone": tone,
        "summary": summary,
        "details": [
            f"run_id={latest_completed['id']}",
            f"newsletter_date={metadata.get('newsletter_date', '')}",
            f"finished={latest_completed.get('finished_at', '')}",
            f"age={_format_age(latest_completed.get('finished_at'))}",
        ],
    }


def build_delivery_status_rows(repository, *, limit: int = 10) -> list[dict]:
    rows: list[dict] = []
    for run in repository.list_recent_delivery_runs(limit=limit) if repository else []:
        metadata = run.get("metadata", {}) or {}
        pipeline_result = metadata.get("pipeline_result", {}) or {}
        rows.append(
            {
                "run_id": run["id"],
                "newsletter_date": str(
                    metadata.get("newsletter_date")
                    or pipeline_result.get("newsletter_date")
                    or ""
                ).strip(),
                "status": str(run.get("status", "")).strip(),
                "finished_at": str(run.get("finished_at", "")).strip(),
                "age": _format_age(run.get("finished_at")),
                "audience_key": str(
                    metadata.get("audience_key")
                    or pipeline_result.get("audience_key")
                    or ""
                ).strip(),
                "sent_recipients": int(pipeline_result.get("sent_recipients", 0) or 0),
                "failed_recipients": int(pipeline_result.get("failed_recipient_count", 0) or 0),
                "cached_newsletter": bool(metadata.get("cached_newsletter", False)),
                "recipient_source": str(pipeline_result.get("recipient_source", "")).strip(),
            }
        )
    return rows


def overall_dashboard_tone(checks: list[dict]) -> str:
    statuses = {str(check.get("status", "")).strip() for check in checks}
    if "error" in statuses:
        return "warning"
    if "warning" in statuses:
        return "info"
    return "success"


def normalize_story_source_name(story: dict) -> dict:
    normalized = dict(story)
    if str(normalized.get("source_type", "")).strip() == "gmail":
        normalized["source_name"] = normalize_gmail_source_name(str(normalized.get("source_name", "")))
    return normalized


def _story_inventory_day(story: dict) -> str:
    raw_timestamp = str(story.get("published_at") or story.get("first_seen_at") or "").strip()
    parsed = _parse_iso_datetime(raw_timestamp)
    if parsed is not None:
        return parsed.date().isoformat()
    if len(raw_timestamp) >= 10:
        raw_day = raw_timestamp[:10]
        try:
            dt.date.fromisoformat(raw_day)
            return raw_day
        except ValueError:
            pass
    return "Unknown"


def build_story_inventory_day_view(stories: list[dict], requested_day: str | None) -> dict:
    day_counts: dict[str, int] = {}
    for story in stories:
        day = _story_inventory_day(story)
        story["inventory_day"] = day
        day_counts[day] = day_counts.get(day, 0) + 1

    sorted_days = sorted(
        day_counts,
        key=lambda day: (day != "Unknown", day),
        reverse=True,
    )
    requested = str(requested_day or "").strip()
    if requested == "all":
        selected_day = "all"
    elif requested in day_counts:
        selected_day = requested
    else:
        selected_day = sorted_days[0] if sorted_days else ""

    if selected_day == "all":
        visible_stories = stories
    elif selected_day:
        visible_stories = [
            story
            for story in stories
            if story.get("inventory_day") == selected_day
        ]
    else:
        visible_stories = []

    return {
        "days": [
            {
                "date": day,
                "count": day_counts[day],
                "is_selected": selected_day == day,
            }
            for day in sorted_days
        ],
        "selected_day": selected_day,
        "visible_stories": visible_stories,
        "total_stories": len(stories),
    }


def build_preview_payload(
    newsletter: dict | None,
    *,
    preview_template: str = "market_tape",
    settings_url: str = "",
) -> dict | None:
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
        email_safe_html = render_email_safe_digest_html(render_groups, settings_url=settings_url)
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


def _metadata_int(metadata: dict, key: str) -> int | None:
    try:
        value = metadata.get(key)
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _newsletter_metadata_with_delivery_fallback(newsletter: dict, repository=None) -> dict:
    metadata = newsletter.get("metadata", {}) or {}
    if all(
        _metadata_int(metadata, key) is not None
        for key in ("gmail_links", "additional_source_links", "eligible_links")
    ):
        return metadata
    if repository is None:
        return metadata

    delivery_run_id = newsletter.get("delivery_run_id")
    if delivery_run_id is None:
        return metadata
    try:
        delivery_run = repository.get_delivery_run(int(delivery_run_id))
    except (AttributeError, TypeError, ValueError):
        return metadata
    if not delivery_run:
        return metadata

    run_metadata = delivery_run.get("metadata", {}) or {}
    pipeline_result = run_metadata.get("pipeline_result", {})
    if not isinstance(pipeline_result, dict):
        return metadata

    merged = dict(pipeline_result)
    merged.update(metadata)
    return merged


def build_newsletter_funnel_stats(newsletter: dict, repository=None) -> dict:
    metadata = _newsletter_metadata_with_delivery_fallback(newsletter, repository)
    selected_items = newsletter.get("selected_items", [])
    selected_items_count = newsletter.get("selected_items_count")
    if selected_items_count is None:
        selected_items_count = (
            len(selected_items) if isinstance(selected_items, list) else 0
        )

    gmail_sourced = _metadata_int(metadata, "gmail_links")
    additional_sourced = _metadata_int(metadata, "additional_source_links")
    total_sourced = _metadata_int(metadata, "eligible_links")
    if total_sourced is None:
        total_sourced = _metadata_int(metadata, "deduped_links")
    if (
        total_sourced is None
        and gmail_sourced is not None
        and additional_sourced is not None
    ):
        total_sourced = gmail_sourced + additional_sourced

    processed = _metadata_int(metadata, "processed_candidates")
    if processed is None:
        accepted_items = _metadata_int(metadata, "accepted_items")
        skipped_count = _metadata_int(metadata, "skipped_count")
        if accepted_items is not None and skipped_count is not None:
            processed = accepted_items + skipped_count
    if processed is None:
        processed = _metadata_int(metadata, "selected")
    if processed is None:
        processed = selected_items_count

    return {
        "total_sourced": total_sourced,
        "gmail_sourced": gmail_sourced,
        "additional_sourced": additional_sourced,
        "processed": processed,
        "selected": selected_items_count,
    }


def build_newsletter_token_stats(newsletter: dict, repository=None) -> dict:
    metadata = _newsletter_metadata_with_delivery_fallback(newsletter, repository)
    total_tokens = _metadata_int(metadata, "total_tokens")

    usage_by_model = metadata.get("usage_by_model", {})
    if total_tokens is None and isinstance(usage_by_model, dict):
        total_tokens = 0
        found_usage = False
        for stats in usage_by_model.values():
            if not isinstance(stats, dict):
                continue
            try:
                total_tokens += int(stats.get("total", 0) or 0)
                found_usage = True
            except (TypeError, ValueError):
                continue
        if not found_usage:
            total_tokens = None

    estimated_cost = estimate_openai_text_cost_usd(usage_by_model)
    return {
        "total": total_tokens,
        "formatted_total": f"{total_tokens:,}" if total_tokens is not None else "n/a",
        "estimated_cost_usd": float(estimated_cost) if estimated_cost is not None else None,
        "formatted_estimated_cost": format_usd_cost(estimated_cost),
    }


def attach_newsletter_funnel_stats(newsletter: dict, repository=None) -> dict:
    return {
        **newsletter,
        "funnel_stats": build_newsletter_funnel_stats(newsletter, repository),
        "token_stats": build_newsletter_token_stats(newsletter, repository),
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


def subscriber_login_turnstile_site_key() -> str:
    return str(os.getenv("CURATOR_TURNSTILE_SITE_KEY", "")).strip()


def subscriber_login_turnstile_secret_key() -> str:
    return str(os.getenv("CURATOR_TURNSTILE_SECRET_KEY", "")).strip()


def subscriber_login_turnstile_enabled() -> bool:
    return bool(subscriber_login_turnstile_site_key() and subscriber_login_turnstile_secret_key())


def subscriber_login_captcha_threshold() -> int:
    try:
        return max(1, int(str(os.getenv("CURATOR_LOGIN_CAPTCHA_THRESHOLD", "")).strip() or "5"))
    except ValueError:
        return 5


def subscriber_login_captcha_window_seconds() -> int:
    try:
        return max(60, int(str(os.getenv("CURATOR_LOGIN_CAPTCHA_WINDOW_SECONDS", "")).strip() or "600"))
    except ValueError:
        return 600


def _subscriber_login_attempt_timestamp() -> float:
    return dt.datetime.now(dt.UTC).timestamp()


def _prune_subscriber_login_attempts(attempts: list[float], *, now: float, window_seconds: int) -> list[float]:
    return [timestamp for timestamp in attempts if (now - timestamp) <= window_seconds]


def subscriber_login_requires_captcha(*, request_ip: str = "", email_address: str = "") -> bool:
    if not subscriber_login_turnstile_enabled():
        return False
    now = _subscriber_login_attempt_timestamp()
    window_seconds = subscriber_login_captcha_window_seconds()
    threshold = subscriber_login_captcha_threshold()
    normalized_ip = str(request_ip or "").strip()
    normalized_email = str(email_address or "").strip().lower()
    with _SUBSCRIBER_LOGIN_ATTEMPT_LOCK:
        ip_attempts = _prune_subscriber_login_attempts(
            list(_SUBSCRIBER_LOGIN_ATTEMPTS["ip"].get(normalized_ip, [])),
            now=now,
            window_seconds=window_seconds,
        )
        if normalized_ip:
            _SUBSCRIBER_LOGIN_ATTEMPTS["ip"][normalized_ip] = ip_attempts
        email_attempts = _prune_subscriber_login_attempts(
            list(_SUBSCRIBER_LOGIN_ATTEMPTS["email"].get(normalized_email, [])),
            now=now,
            window_seconds=window_seconds,
        )
        if normalized_email:
            _SUBSCRIBER_LOGIN_ATTEMPTS["email"][normalized_email] = email_attempts
    return len(ip_attempts) >= threshold or len(email_attempts) >= threshold


def record_subscriber_login_attempt(*, request_ip: str = "", email_address: str = "") -> None:
    now = _subscriber_login_attempt_timestamp()
    window_seconds = subscriber_login_captcha_window_seconds()
    normalized_ip = str(request_ip or "").strip()
    normalized_email = str(email_address or "").strip().lower()
    with _SUBSCRIBER_LOGIN_ATTEMPT_LOCK:
        if normalized_ip:
            ip_attempts = _prune_subscriber_login_attempts(
                list(_SUBSCRIBER_LOGIN_ATTEMPTS["ip"].get(normalized_ip, [])),
                now=now,
                window_seconds=window_seconds,
            )
            ip_attempts.append(now)
            _SUBSCRIBER_LOGIN_ATTEMPTS["ip"][normalized_ip] = ip_attempts
        if normalized_email:
            email_attempts = _prune_subscriber_login_attempts(
                list(_SUBSCRIBER_LOGIN_ATTEMPTS["email"].get(normalized_email, [])),
                now=now,
                window_seconds=window_seconds,
            )
            email_attempts.append(now)
            _SUBSCRIBER_LOGIN_ATTEMPTS["email"][normalized_email] = email_attempts


def subscriber_signup_url() -> str:
    configured = str(os.getenv("CURATOR_SUBSCRIBER_SIGNUP_URL", "")).strip()
    if configured:
        return configured
    return DEFAULT_SUBSCRIBER_SIGNUP_URL


def subscriber_email_is_registered(config: dict, email_address: str) -> bool:
    from curator.jobs import resolve_digest_recipients

    recipients, _recipient_source = resolve_digest_recipients(config)
    return str(email_address or "").strip().lower() in set(recipients)


def verify_subscriber_login_turnstile(token: str, *, remoteip: str = "") -> tuple[bool, str]:
    if not subscriber_login_turnstile_enabled():
        return True, ""
    normalized_token = str(token or "").strip()
    if not normalized_token:
        return False, "Complete the CAPTCHA challenge and try again."
    try:
        response = requests.post(
            TURNSTILE_VERIFY_URL,
            data={
                "secret": subscriber_login_turnstile_secret_key(),
                "response": normalized_token,
                "remoteip": str(remoteip or "").strip(),
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return False, "CAPTCHA verification is unavailable right now. Try again shortly."
    if bool(payload.get("success")):
        return True, ""
    return False, "Complete the CAPTCHA challenge and try again."


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
    configured = resolve_public_base_url()
    if configured:
        return configured
    return request.url_root.rstrip("/")


def build_subscriber_login_confirm_url(raw_token: str) -> str:
    return f"{subscriber_public_base_url()}{url_for('confirm_subscriber_login', token=raw_token)}"


def send_subscriber_login_email(config: dict, to_address: str, confirm_url: str) -> dict:
    from curator.gmail import get_gmail_service, send_email

    credentials_path = resolve_path_from_config(config.get("paths", {}).get("credentials", ""))
    token_path = resolve_path_from_config(config.get("paths", {}).get("token", ""))
    if not credentials_path.exists() or not token_path.exists():
        return {"sent": False, "error": "gmail_credentials_unavailable"}
    subject = "Your AI Signal Daily sign-in link"
    body = (
        "Use this secure sign-in link to access your AI Signal Daily settings in Newsletter Curator:\n\n"
        f"{confirm_url}\n\n"
        f"This link expires in {SUBSCRIBER_LOGIN_TOKEN_TTL_MINUTES} minutes. "
        "If you did not request it, you can ignore this email."
    )
    html_body = render_template(
        "subscriber_login_email.html",
        confirm_url=confirm_url,
        ttl_minutes=SUBSCRIBER_LOGIN_TOKEN_TTL_MINUTES,
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
            _normalize_origin(resolve_public_base_url()),
            _normalize_origin(request.url_root),
        }
        if origin
    }
    return origins


def configured_app_host() -> str:
    return (
        os.getenv("CURATOR_APP_HOST", "").strip()
        or os.getenv("CURATOR_ADMIN_HOST", "").strip()
        or "127.0.0.1"
    )


def configured_app_port() -> int:
    raw_value = (
        os.getenv("CURATOR_APP_PORT", "").strip()
        or os.getenv("CURATOR_ADMIN_PORT", "").strip()
        or "8080"
    )
    return int(raw_value)


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
    captcha_required: bool = False,
    turnstile_site_key: str = "",
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
            captcha_required=captcha_required,
            turnstile_site_key=turnstile_site_key,
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
    selected_lookup = {
        str(source).strip().lower()
        for source in selected_sources
        if str(source).strip()
    }
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
            "additional_sources.max_total",
            form.get("additional_max_total", "").strip()
            or str(DEFAULT_CONFIG["additional_sources"]["max_total"]),
            1,
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
        return redirect(url_for("subscriber_settings"))

    message = ""
    errors: list[str] = []
    login_link = ""
    login_delivery_status = ""
    email_address = ""
    captcha_required = subscriber_login_requires_captcha(request_ip=_request_ip())
    turnstile_site_key = subscriber_login_turnstile_site_key() if captcha_required else ""

    if request.method == "POST":
        request_ip = _request_ip()
        email_address = normalize_email_address(request.form.get("email_address", ""))
        captcha_required = subscriber_login_requires_captcha(
            request_ip=request_ip,
            email_address=email_address,
        )
        turnstile_site_key = subscriber_login_turnstile_site_key() if captcha_required else ""
        redirect_response = None

        if captcha_required:
            verified, captcha_error = verify_subscriber_login_turnstile(
                request.form.get("cf-turnstile-response", ""),
                remoteip=request_ip,
            )
            if not verified:
                errors.append(captcha_error)
        if not errors:
            if not email_address:
                errors.append("Enter a valid email address.")
            elif not subscriber_email_is_registered(merged, email_address):
                redirect_response = redirect(subscriber_signup_url())
            elif repository is None:
                errors.append("Subscriber login is unavailable because the repository could not be opened.")
            else:
                subscriber = repository.upsert_subscriber(email_address)
                token_payload = repository.create_subscriber_login_token(
                    int(subscriber["id"]),
                    ttl_minutes=SUBSCRIBER_LOGIN_TOKEN_TTL_MINUTES,
                    request_ip=request_ip,
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

        record_subscriber_login_attempt(request_ip=request_ip, email_address=email_address)
        if redirect_response is not None:
            return redirect_response

    if request.args.get("logged_out", "").strip() == "1" and not (message or errors):
        message = "You have been signed out."
    return render_subscriber_login_page(
        email_address=email_address,
        message=message,
        errors=errors,
        login_link=login_link if subscriber_login_link_exposure_enabled() else "",
        login_delivery_status=login_delivery_status,
        captcha_required=captcha_required,
        turnstile_site_key=turnstile_site_key,
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
    response = redirect(url_for("subscriber_settings"))
    set_subscriber_session_cookie(response, session_payload["token"])
    return response


@app.route("/account", methods=["GET"])
def subscriber_account():
    return redirect(url_for("subscriber_settings"))


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
        "profile_exists": False,
        "persona_text": "",
        "delivery_format": "email",
        "preferred_sources": [],
        "created_at": "",
        "updated_at": "",
    }
    if repository is not None and not bool(profile.get("profile_exists")):
        from curator.jobs import default_preferred_sources

        seeded_defaults = default_preferred_sources(available_sources)
        if seeded_defaults:
            profile = repository.upsert_subscriber_profile(
                int(subscriber["id"]),
                preferred_sources=seeded_defaults,
            )
    errors: list[str] = []
    message = ""

    if request.method == "POST":
        from curator.repository import normalize_subscriber_delivery_format

        persona_text = str(request.form.get("persona_text", "") or "").strip()
        if "pdf_delivery_enabled" in request.form:
            delivery_format = "pdf"
        elif "delivery_format" in request.form:
            delivery_format = normalize_subscriber_delivery_format(
                str(request.form.get("delivery_format", "") or "").strip()
            )
        else:
            delivery_format = "email"
        preferred_sources = normalize_subscriber_preferred_sources(
            request.form,
            available_sources=available_sources,
            current_profile=profile,
        )
        profile = repository.upsert_subscriber_profile(
            int(subscriber["id"]),
            persona_text=persona_text,
            delivery_format=delivery_format,
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
    settings_url = build_settings_url(resolve_tracking_base_url(merged))
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
            preview = build_preview_payload(
                cached_newsletter,
                preview_template=preview_template,
                settings_url=settings_url,
            )
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
            preview = build_preview_payload(
                cached_newsletter,
                preview_template=preview_template,
                settings_url=settings_url,
            )
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
    newsletters = (
        [
            attach_newsletter_funnel_stats(newsletter, repository)
            for newsletter in repository.list_daily_newsletters(
                limit=30,
                include_all_audiences=True,
                one_per_date=True,
            )
        ]
        if repository
        else []
    )
    response = make_response(
        render_admin_template(
            "newsletter_history.html",
            config_path=CONFIG_PATH,
            newsletters=newsletters,
        )
    )
    return response


@app.route("/inventory", methods=["GET"])
def repository_inventory():
    _admin_token, redirect_response = require_admin_browser_auth()
    if redirect_response is not None:
        return redirect_response
    merged = load_merged_config()
    repository = load_repository(merged)
    all_active_stories = repository.list_stories() if repository else []
    all_active_stories = [
        normalize_story_source_name(story)
        for story in all_active_stories
    ]
    inventory_view = build_story_inventory_day_view(
        all_active_stories,
        request.args.get("inventory_day"),
    )
    response = make_response(
        render_admin_template(
            "repository_inventory.html",
            config_path=CONFIG_PATH,
            active_stories=inventory_view["visible_stories"],
            active_story_total=inventory_view["total_stories"],
            inventory_days=inventory_view["days"],
            selected_inventory_day=inventory_view["selected_day"],
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
    newsletter = (
        repository.get_daily_newsletter(newsletter_date, include_all_audiences=True)
        if repository
        else None
    )
    if newsletter is None:
        abort(404)
    newsletter = attach_newsletter_funnel_stats(newsletter, repository)

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
    recent_newsletters = (
        repository.list_newsletter_analytics(limit=7, include_all_audiences=True)
        if repository
        else []
    )
    window_stats = (
        repository.get_newsletter_aggregate_stats(include_all_audiences=True)
        if repository
        else []
    )
    top_clicked_stories = (
        repository.list_top_clicked_stories(
            trailing_days=30,
            limit=10,
            include_all_audiences=True,
        )
        if repository
        else []
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


@app.route("/operations", methods=["GET"])
def operations_dashboard():
    _admin_token, redirect_response = require_admin_browser_auth()
    if redirect_response is not None:
        return redirect_response
    merged, config_state = load_dashboard_config_state()
    repository, sqlite_check = open_repository_status(merged)
    checks = [
        sqlite_check,
        build_config_validity_check(merged, config_state),
        build_gmail_auth_presence_check(merged),
        build_public_base_url_check(merged),
        build_ingest_freshness_check(merged, repository),
        build_delivery_freshness_check(repository),
    ]
    recent_delivery_rows = build_delivery_status_rows(repository, limit=10)
    response = make_response(
        render_admin_template(
            "health_dashboard.html",
            config_path=CONFIG_PATH,
            checks=checks,
            overall_tone=overall_dashboard_tone(checks),
            recent_delivery_rows=recent_delivery_rows,
        )
    )
    return response


if __name__ == "__main__":
    app.run(host=configured_app_host(), port=configured_app_port(), debug=False)
