import datetime as dt
import os
from pathlib import Path

from flask import Flask, abort, make_response, redirect, render_template, request, url_for
import yaml

from curator.jobs import get_repository_from_config
from main import CONFIG_PATH, DEFAULT_CONFIG, merge_dicts, preview_job


app = Flask(__name__)
ADMIN_TOKEN_COOKIE = "curator_admin_token"


def load_config_file() -> dict:
    path = Path(CONFIG_PATH)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_merged_config() -> dict:
    return merge_dicts(DEFAULT_CONFIG, load_config_file())


def load_repository(config: dict):
    try:
        return get_repository_from_config(config)
    except Exception:
        return None


def get_provided_admin_token() -> str:
    return (
        request.headers.get("X-Admin-Token", "").strip()
        or request.args.get("token", "").strip()
        or request.form.get("token", "").strip()
        or request.cookies.get(ADMIN_TOKEN_COOKIE, "").strip()
    )


def require_admin_token() -> str:
    expected = os.getenv("CURATOR_ADMIN_TOKEN", "").strip()
    if not expected:
        return ""
    provided = get_provided_admin_token()
    if provided != expected:
        abort(401)
    return provided


def resolve_request_token(provided_token: str) -> str:
    return (
        request.args.get("token", "").strip()
        or request.form.get("token", "").strip()
        or provided_token
    )


def parse_bool(value: str | None) -> bool:
    return str(value or "").lower() in {"1", "true", "yes", "on"}


def parse_int(name: str, value: str, min_value: int = 0) -> int:
    parsed = int(value)
    if parsed < min_value:
        raise ValueError(f"{name} must be >= {min_value}")
    return parsed


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


@app.errorhandler(401)
def unauthorized(_):
    return (
        "Unauthorized. Provide CURATOR_ADMIN_TOKEN via '?token=YOUR_TOKEN' "
        "or header 'X-Admin-Token'.",
        401,
    )


@app.route("/", methods=["GET", "POST"])
def config_editor():
    provided_token = require_admin_token()
    token_from_request = resolve_request_token(provided_token)
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
            response = redirect(
                url_for("config_editor", saved="1", token=token_from_request or None)
            )
            if token_from_request:
                response.set_cookie(
                    ADMIN_TOKEN_COOKIE,
                    token_from_request,
                    httponly=True,
                    samesite="Lax",
                )
            return response
        merged = merge_dicts(DEFAULT_CONFIG, updated_raw)
        repository = load_repository(merged)
        available_sources = repository.list_sources_with_selection() if repository else []

    if request.args.get("saved") == "1":
        message = f"Saved {CONFIG_PATH} successfully."

    response = make_response(
        render_template(
            "admin_config.html",
            config=merged,
            config_path=CONFIG_PATH,
            available_sources=available_sources,
            message=message,
            errors=errors,
            token=token_from_request,
            token_note=(
                "Token auth is active via session cookie."
                if os.getenv("CURATOR_ADMIN_TOKEN", "").strip()
                and not request.args.get("token", "").strip()
                else ""
            ),
        )
    )
    if request.args.get("token", "").strip():
        response.set_cookie(
            ADMIN_TOKEN_COOKIE,
            request.args.get("token", "").strip(),
            httponly=True,
            samesite="Lax",
        )
    return response


@app.route("/preview", methods=["GET"])
def preview_newsletter():
    provided_token = require_admin_token()
    token_from_request = resolve_request_token(provided_token)
    merged = load_merged_config()
    error = ""
    preview = None
    result = None
    status_code = 200

    try:
        result = preview_job(merged)
        preview = result.get("preview")
        if preview is None:
            error = "Preview generation completed but did not produce a digest."
            status_code = 500
    except Exception as exc:
        error = str(exc)
        status_code = 500

    response = make_response(
        render_template(
            "digest_preview.html",
            config_path=CONFIG_PATH,
            preview=preview,
            result=result,
            error=error,
            token=token_from_request,
        ),
        status_code,
    )
    if token_from_request:
        response.set_cookie(
            ADMIN_TOKEN_COOKIE,
            token_from_request,
            httponly=True,
            samesite="Lax",
        )
    return response


if __name__ == "__main__":
    host = os.getenv("CURATOR_ADMIN_HOST", "127.0.0.1")
    port = int(os.getenv("CURATOR_ADMIN_PORT", "8080"))
    app.run(host=host, port=port, debug=False)
