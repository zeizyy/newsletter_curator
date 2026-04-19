from __future__ import annotations

import json
import traceback

from .debug_logs import configured_debug_log_path, read_debug_log_tail, validate_configured_debug_log_path
from .observability import recent_event_lines


DELIVERY_FAILURE_ALERT_LOG_LINES = 80


def _sanitize_failed_recipient(entry: dict) -> dict:
    return {
        "recipient": str(entry.get("recipient", "")).strip(),
        "attempts": int(entry.get("attempts", 0) or 0),
        "error": str(entry.get("error", "")).strip(),
        "error_type": str(entry.get("error_type", "")).strip(),
        "error_status_code": entry.get("error_status_code"),
        "error_code": str(entry.get("error_code", "")).strip(),
        "retryable": bool(entry.get("retryable", False)),
        "message_id_header": str(entry.get("message_id_header", "")).strip(),
    }


def _sanitize_delivery_group(entry: dict) -> dict:
    return {
        "profile_key": str(entry.get("profile_key", "")).strip(),
        "audience_key": str(entry.get("audience_key", "")).strip(),
        "delivery_format": str(entry.get("delivery_format", "")).strip(),
        "recipients": list(entry.get("recipients", []) or []),
        "sent_recipients": int(entry.get("sent_recipients", 0) or 0),
        "failed_recipient_count": int(entry.get("failed_recipient_count", 0) or 0),
        "failed_recipients": [
            _sanitize_failed_recipient(item) for item in list(entry.get("failed_recipients", []) or [])
        ],
        "status": str(entry.get("status", "")).strip(),
    }


def summarize_delivery_result_for_alert(result: dict | None) -> dict:
    if not isinstance(result, dict):
        return {}

    stages = result.get("stages")
    if isinstance(stages, dict):
        delivery_stage = stages.get("deliver_digest")
        summary = {
            "status": str(result.get("status", "")).strip(),
            "completed_stages": list(result.get("completed_stages", []) or []),
            "partial_failure_stages": list(result.get("partial_failure_stages", []) or []),
            "failed_stages": list(result.get("failed_stages", []) or []),
            "failures": list(result.get("failures", []) or []),
        }
        if isinstance(delivery_stage, dict):
            summary["deliver_digest"] = summarize_delivery_result_for_alert(delivery_stage)
        return summary

    summary = {
        "status": str(result.get("status", "")).strip(),
        "run_id": result.get("run_id"),
        "newsletter_date": str(result.get("newsletter_date", "")).strip(),
        "audience_key": str(result.get("audience_key", "")).strip(),
        "delivery_format": str(result.get("delivery_format", "")).strip(),
        "recipient_source": str(result.get("recipient_source", "")).strip(),
        "cached_newsletter": bool(result.get("cached_newsletter", False)),
        "personalized_delivery": bool(result.get("personalized_delivery", False)),
        "sent_recipients": int(result.get("sent_recipients", 0) or 0),
        "failed_recipient_count": int(result.get("failed_recipient_count", 0) or 0),
        "failed_recipients": [
            _sanitize_failed_recipient(item) for item in list(result.get("failed_recipients", []) or [])
        ],
    }
    delivery_groups = list(result.get("delivery_groups", []) or [])
    if delivery_groups:
        summary["delivery_groups"] = [_sanitize_delivery_group(item) for item in delivery_groups]
    return summary


def delivery_failure_requires_alert(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    stages = result.get("stages")
    if isinstance(stages, dict):
        delivery_stage = stages.get("deliver_digest")
        if not isinstance(delivery_stage, dict):
            return False
        status = str(delivery_stage.get("status", "")).strip()
        return bool(status and status not in {"completed", "skipped"})
    status = str(result.get("status", "")).strip()
    return bool(status and status not in {"completed", "skipped"})


def collect_recent_debug_log_context(*, lines: int = DELIVERY_FAILURE_ALERT_LOG_LINES) -> dict:
    path, status = validate_configured_debug_log_path(configured_debug_log_path())
    if path is None or status != "ok":
        in_memory_lines = recent_event_lines(lines)
        return {
            "status": "memory_fallback" if in_memory_lines else status,
            "path": str(path) if path is not None else "",
            "lines": in_memory_lines,
            "truncated": False,
            "source_paths": [],
        }
    tail_lines, truncated, source_paths = read_debug_log_tail(path, lines=lines, merged=True)
    return {
        "status": "ok",
        "path": str(path),
        "lines": tail_lines,
        "truncated": truncated,
        "source_paths": source_paths,
    }


def build_delivery_failure_alert_subject(
    config: dict,
    *,
    source: str,
    result: dict | None = None,
    exception: Exception | None = None,
) -> str:
    prefix = str(config.get("email", {}).get("alert_subject_prefix", "")).strip() or "[ALERT]"
    if exception is not None:
        status = "failed"
    elif isinstance(result, dict) and isinstance(result.get("stages"), dict):
        status = str(result.get("stages", {}).get("deliver_digest", {}).get("status", "")).strip() or "failed"
    else:
        status = str((result or {}).get("status", "")).strip() or "failed"
    return f"{prefix}: {status} [{source}]"


def build_delivery_failure_alert_body(
    *,
    source: str,
    result: dict | None = None,
    exception: Exception | None = None,
    traceback_text: str = "",
    debug_log_lines: int = DELIVERY_FAILURE_ALERT_LOG_LINES,
) -> str:
    summary = summarize_delivery_result_for_alert(result)
    debug_log_context = collect_recent_debug_log_context(lines=debug_log_lines)

    lines = [
        "Newsletter Curator delivery failure alert",
        "",
        f"Source: {source}",
        f"Alert status: {summary.get('status', 'failed') if summary else 'failed'}",
    ]

    failed_recipients = list(summary.get("failed_recipients", []) or [])
    if not failed_recipients and isinstance(summary.get("deliver_digest"), dict):
        failed_recipients = list(summary["deliver_digest"].get("failed_recipients", []) or [])
    if not failed_recipients:
        for group in list(summary.get("delivery_groups", []) or []):
            failed_recipients.extend(list(group.get("failed_recipients", []) or []))

    if failed_recipients:
        lines.extend(["", "Failed recipients:"])
        for recipient in failed_recipients:
            exact_codes: list[str] = []
            if recipient.get("error_status_code") is not None:
                exact_codes.append(f"status_code={recipient['error_status_code']}")
            if str(recipient.get("error_code", "")).strip():
                exact_codes.append(f"error_code={recipient['error_code']}")
            error_type = str(recipient.get("error_type", "")).strip()
            if error_type:
                exact_codes.append(f"error_type={error_type}")
            rendered_codes = ", ".join(exact_codes) or "unavailable"
            lines.append(
                (
                    f"- recipient={recipient.get('recipient', '')} "
                    f"attempts={recipient.get('attempts', 0)} "
                    f"retryable={recipient.get('retryable', False)} "
                    f"exact_error_code={rendered_codes} "
                    f"error={recipient.get('error', '')}"
                )
            )

    if exception is not None:
        lines.extend(
            [
                "",
                "Exception:",
                f"- type={exception.__class__.__name__}",
                f"- error={str(exception)}",
            ]
        )
        rendered_traceback = traceback_text.strip() or traceback.format_exc().strip()
        if rendered_traceback:
            lines.extend(["", "Traceback:", rendered_traceback])

    if summary:
        lines.extend(["", "Failure summary:", json.dumps(summary, indent=2, sort_keys=True)])

    lines.extend(["", "Recent debug log tail:"])
    if debug_log_context["status"] == "memory_fallback":
        lines.append("Source: in-memory event buffer (debug log path unavailable).")
        lines.extend(debug_log_context["lines"] or ["(event buffer is empty)"])
    elif debug_log_context["status"] != "ok":
        lines.append(
            f"Debug log tail unavailable: status={debug_log_context['status']} path={debug_log_context['path']}"
        )
    else:
        lines.append(
            f"Source paths: {', '.join(debug_log_context['source_paths']) or debug_log_context['path']}"
        )
        if debug_log_context["truncated"]:
            lines.append(f"Showing last {debug_log_lines} lines.")
        lines.extend(debug_log_context["lines"] or ["(debug log is empty)"])

    return "\n".join(lines).strip()


def send_delivery_failure_alert_if_needed(
    config: dict,
    service,
    *,
    send_email_fn,
    source: str,
    result: dict | None = None,
    exception: Exception | None = None,
    traceback_text: str = "",
    debug_log_lines: int = DELIVERY_FAILURE_ALERT_LOG_LINES,
) -> bool:
    alert_recipient = str(config.get("email", {}).get("alert_recipient", "")).strip()
    if service is None or not alert_recipient:
        return False
    if exception is None and not delivery_failure_requires_alert(result):
        return False

    send_email_fn(
        service,
        to_address=alert_recipient,
        subject=build_delivery_failure_alert_subject(
            config,
            source=source,
            result=result,
            exception=exception,
        ),
        body=build_delivery_failure_alert_body(
            source=source,
            result=result,
            exception=exception,
            traceback_text=traceback_text,
            debug_log_lines=debug_log_lines,
        ),
    )
    return True
