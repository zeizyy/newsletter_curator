from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import email.utils
from email.message import EmailMessage
import hashlib
import inspect
import json
import time
from typing import Iterable
from datetime import UTC

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
DELIVERY_SEND_MAX_ATTEMPTS = 3
DELIVERY_SEND_INITIAL_BACKOFF_SECONDS = 1.0


def load_credentials(paths: dict) -> Credentials:
    token_path = paths["token"]
    creds = None
    if paths and token_path:
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except FileNotFoundError:
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(paths["credentials"], SCOPES)
            flow.redirect_uri = "http://localhost"
            auth_url, _ = flow.authorization_url(prompt="consent")
            print(f"Authorize this app by visiting:\n{auth_url}\n")
            code = input("Enter the authorization code: ").strip()
            flow.fetch_token(code=code)
            creds = flow.credentials
        with open(token_path, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())
    return creds


def get_gmail_service(paths: dict):
    creds = load_credentials(paths)
    return build("gmail", "v1", credentials=creds)


def list_message_ids_for_label(service, label_id: str, query: str) -> list[str]:
    message_ids = []
    page_token = None
    while True:
        response = (
            service.users()
            .messages()
            .list(userId="me", labelIds=[label_id], q=query, pageToken=page_token)
            .execute()
        )
        message_ids.extend([msg["id"] for msg in response.get("messages", [])])
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return message_ids


def get_message(service, message_id: str) -> dict:
    return (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )


def list_message_ids(service, *, query: str, label_ids: list[str] | None = None) -> list[str]:
    message_ids = []
    page_token = None
    while True:
        request = service.users().messages().list(
            userId="me",
            labelIds=list(label_ids or []),
            q=query,
            pageToken=page_token,
        )
        response = request.execute()
        message_ids.extend([msg["id"] for msg in response.get("messages", [])])
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return message_ids


def normalize_message_id_header(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("<") and normalized.endswith(">"):
        return normalized
    return f"<{normalized.strip('<>')}>"


def message_exists_in_sent(service, *, message_id_header: str) -> bool:
    normalized = normalize_message_id_header(message_id_header)
    if not normalized:
        return False
    return bool(
        list_message_ids(
            service,
            query=f"rfc822msgid:{normalized}",
            label_ids=["SENT"],
        )
    )


def _sent_message_lookup_error_event(exc: Exception, *, attempt: int) -> dict:
    error_details = _delivery_send_error_details(exc)
    return {
        "event": "sent_lookup_failed",
        "attempt": attempt,
        "error": error_details["error"],
        "error_type": error_details["error_type"],
        "error_status_code": error_details["error_status_code"],
        "error_code": error_details["error_code"],
    }


def _delivery_send_error_status_code(exc: Exception) -> int | None:
    response = getattr(exc, "resp", None)
    status = getattr(response, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _delivery_send_error_code(exc: Exception) -> str:
    for attribute_name in ("errno", "code"):
        value = getattr(exc, attribute_name, None)
        if value is None:
            continue
        rendered = str(value).strip()
        if rendered:
            return rendered
    return ""


def _delivery_send_error_details(exc: Exception) -> dict:
    return {
        "error": str(exc),
        "error_type": exc.__class__.__name__,
        "error_status_code": _delivery_send_error_status_code(exc),
        "error_code": _delivery_send_error_code(exc),
    }


def is_retryable_delivery_send_error(exc: Exception) -> bool:
    if isinstance(exc, OSError):
        return True
    status_code = _delivery_send_error_status_code(exc)
    if status_code is None:
        return False
    return status_code in {408, 429} or status_code >= 500


def is_ambiguous_delivery_send_error(exc: Exception) -> bool:
    if isinstance(exc, OSError):
        return True
    return _delivery_send_error_status_code(exc) is None


def supports_message_id_header(send_email_fn) -> bool:
    return _supports_keyword_argument(send_email_fn, "message_id_header")


def supports_attachments(send_email_fn) -> bool:
    return _supports_keyword_argument(send_email_fn, "attachments")


def _supports_keyword_argument(send_email_fn, parameter_name: str) -> bool:
    try:
        signature = inspect.signature(send_email_fn)
    except (TypeError, ValueError):
        return False
    parameter = signature.parameters.get(parameter_name)
    if parameter is None:
        return False
    return parameter.kind in {
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }


def build_delivery_message_id(
    *,
    newsletter_date: str,
    audience_key: str,
    daily_newsletter_id: int | None,
    recipient: str,
) -> str:
    payload = json.dumps(
        {
            "newsletter_date": newsletter_date,
            "audience_key": str(audience_key or "").strip(),
            "daily_newsletter_id": int(daily_newsletter_id or 0),
            "recipient": str(recipient or "").strip().lower(),
        },
        sort_keys=True,
    )
    token = hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()
    return f"<delivery-{token}@newsletter-curator.local>"


def send_email_with_retry_and_dedupe(
    service,
    send_email_fn,
    *,
    to_address: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: list[dict] | None = None,
    newsletter_date: str,
    audience_key: str,
    daily_newsletter_id: int | None,
    message_id_header: str = "",
    max_attempts: int = DELIVERY_SEND_MAX_ATTEMPTS,
    initial_backoff_seconds: float = DELIVERY_SEND_INITIAL_BACKOFF_SECONDS,
    sleep_fn=time.sleep,
) -> dict:
    message_id_header = normalize_message_id_header(message_id_header) or build_delivery_message_id(
        newsletter_date=newsletter_date,
        audience_key=audience_key,
        daily_newsletter_id=daily_newsletter_id,
        recipient=to_address,
    )
    send_email_supports_message_id = supports_message_id_header(send_email_fn)
    send_email_supports_attachments = supports_attachments(send_email_fn)
    events: list[dict] = []
    attempt = 0
    while attempt < max_attempts:
        if service is not None:
            try:
                existing_message_sent = message_exists_in_sent(
                    service,
                    message_id_header=message_id_header,
                )
            except Exception as exc:
                events.append(_sent_message_lookup_error_event(exc, attempt=attempt + 1))
                existing_message_sent = False
            if existing_message_sent:
                return {
                    "status": "sent",
                    "recipient": to_address,
                    "message_id_header": message_id_header,
                    "attempts": attempt,
                    "error": "",
                    "retryable": False,
                    "events": events
                    + [
                        {
                            "event": "skipped_existing",
                            "attempt": attempt + 1,
                        }
                    ],
                }
        attempt += 1
        try:
            send_kwargs = {}
            if send_email_supports_message_id:
                send_kwargs["message_id_header"] = message_id_header
            if send_email_supports_attachments and attachments:
                send_kwargs["attachments"] = attachments
            send_email_fn(
                service,
                to_address=to_address,
                subject=subject,
                body=body,
                html_body=html_body,
                **send_kwargs,
            )
        except Exception as exc:
            error_details = _delivery_send_error_details(exc)
            last_error = error_details["error"]
            retryable = is_retryable_delivery_send_error(exc)
            if service is not None and is_ambiguous_delivery_send_error(exc):
                try:
                    existing_message_sent = message_exists_in_sent(
                        service,
                        message_id_header=message_id_header,
                    )
                except Exception as lookup_exc:
                    events.append(_sent_message_lookup_error_event(lookup_exc, attempt=attempt))
                    existing_message_sent = False
                if existing_message_sent:
                    return {
                        "status": "sent",
                        "recipient": to_address,
                        "message_id_header": message_id_header,
                        "attempts": attempt,
                        "error": last_error,
                        "error_type": error_details["error_type"],
                        "error_status_code": error_details["error_status_code"],
                        "error_code": error_details["error_code"],
                        "retryable": retryable,
                        "events": events
                        + [
                            {
                                "event": "verified_after_error",
                                "attempt": attempt,
                                "error": last_error,
                                "error_type": error_details["error_type"],
                                "error_status_code": error_details["error_status_code"],
                                "error_code": error_details["error_code"],
                            }
                        ],
                    }
            if retryable and attempt < max_attempts:
                events.append(
                    {
                        "event": "retry",
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "error": last_error,
                        "error_type": error_details["error_type"],
                        "error_status_code": error_details["error_status_code"],
                        "error_code": error_details["error_code"],
                    }
                )
                sleep_fn(initial_backoff_seconds * (2 ** (attempt - 1)))
                continue
            return {
                "status": "failed",
                "recipient": to_address,
                "message_id_header": message_id_header,
                "attempts": attempt,
                "error": last_error,
                "error_type": error_details["error_type"],
                "error_status_code": error_details["error_status_code"],
                "error_code": error_details["error_code"],
                "retryable": retryable,
                "events": events
                + [
                    {
                        "event": "failed",
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "error": last_error,
                        "error_type": error_details["error_type"],
                        "error_status_code": error_details["error_status_code"],
                        "error_code": error_details["error_code"],
                        "retryable": retryable,
                    }
                ],
            }
        return {
            "status": "sent",
            "recipient": to_address,
            "message_id_header": message_id_header,
            "attempts": attempt,
            "error": "",
            "retryable": False,
            "events": events + [{"event": "completed", "attempt": attempt}],
        }

    return {
        "status": "failed",
        "recipient": to_address,
        "message_id_header": message_id_header,
        "attempts": max_attempts,
        "error": "send attempts exhausted",
        "retryable": True,
        "events": events,
    }


def decode_base64url(data: str) -> str:
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


def walk_parts(payload: dict) -> Iterable[dict]:
    stack = [payload]
    while stack:
        part = stack.pop()
        if "parts" in part:
            stack.extend(part["parts"])
        else:
            yield part


def extract_bodies(payload: dict) -> tuple[list[str], list[str]]:
    text_bodies = []
    html_bodies = []
    for part in walk_parts(payload):
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if not data:
            continue
        decoded = decode_base64url(data)
        if mime_type == "text/plain":
            text_bodies.append(decoded)
        elif mime_type == "text/html":
            html_bodies.append(decoded)
    return text_bodies, html_bodies


def get_header_value(headers: list[dict], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def get_label_id(service, label_name: str) -> str:
    response = service.users().labels().list(userId="me").execute()
    for label in response.get("labels", []):
        if label.get("name") == label_name:
            return label.get("id", "")
    raise ValueError(f"Label not found: {label_name}")


def parse_email_datetime(value: str) -> str:
    if not value.strip():
        return ""
    parsed = email.utils.parsedate_to_datetime(value)
    return parsed.astimezone(UTC).isoformat() if parsed else ""


def normalize_gmail_source_name(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "gmail"
    display_name, email_address = email.utils.parseaddr(raw)
    display_name = display_name.strip()
    email_address = email_address.strip()
    if display_name:
        return display_name
    if email_address:
        return email_address
    return raw


def collect_live_gmail_links(
    service,
    config: dict,
    *,
    get_label_id_fn=get_label_id,
    list_message_ids_for_label_fn=list_message_ids_for_label,
    get_message_fn=get_message,
    extract_bodies_fn=extract_bodies,
    get_header_value_fn=get_header_value,
    extract_links_from_html_fn=None,
) -> list[dict]:
    if extract_links_from_html_fn is None:
        raise ValueError("extract_links_from_html_fn is required")

    gmail_cfg = config["gmail"]
    limits_cfg = config["limits"]
    query = gmail_cfg["query_time_window"]
    label_id = get_label_id_fn(service, gmail_cfg["label"])
    message_ids = list_message_ids_for_label_fn(service, label_id, query)
    configured_workers = max(1, int(limits_cfg.get("max_gmail_message_workers", 5) or 5))
    worker_count = min(configured_workers, len(message_ids)) if message_ids else 0

    def collect_one(message_id: str) -> list[dict]:
        message = get_message_fn(service, message_id)
        payload = message.get("payload", {})
        headers = payload.get("headers", [])
        subject = get_header_value_fn(headers, "Subject")
        from_header = get_header_value_fn(headers, "From")
        source_name = normalize_gmail_source_name(from_header)
        date_header = get_header_value_fn(headers, "Date")
        email_sent_at = parse_email_datetime(date_header)

        _text_bodies, html_bodies = extract_bodies_fn(payload)
        links = []
        for html in html_bodies:
            links.extend(extract_links_from_html_fn(html))
        links = links[: limits_cfg["max_links_per_email"]]
        message_links = []
        for link in links:
            message_links.append(
                {
                    "subject": subject,
                    "from": from_header,
                    "source_name": source_name,
                    "source_type": "gmail",
                    "date": date_header,
                    "email_sent_at": email_sent_at,
                    "published_at": email_sent_at,
                    "url": link["url"],
                    "anchor_text": link["anchor_text"],
                    "context": link["context"],
                }
            )
        return message_links

    if worker_count <= 1:
        all_links: list[dict] = []
        for message_id in message_ids:
            all_links.extend(collect_one(message_id))
        return all_links

    links_by_index: list[list[dict] | None] = [None] * len(message_ids)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(collect_one, message_id): index
            for index, message_id in enumerate(message_ids)
        }
        for future in as_completed(futures):
            links_by_index[futures[future]] = future.result()

    all_links = []
    for links in links_by_index:
        all_links.extend(links or [])
    return all_links


def gmail_query_cutoff(query: str) -> str | None:
    query = query.strip().lower()
    if query.startswith("newer_than:") and query.endswith("d"):
        try:
            days = int(query.removeprefix("newer_than:")[:-1])
        except ValueError:
            return None
        from datetime import UTC, datetime, timedelta

        return (datetime.now(UTC) - timedelta(days=days)).isoformat()
    if query.startswith("newer_than:") and query.endswith("h"):
        try:
            hours = int(query.removeprefix("newer_than:")[:-1])
        except ValueError:
            return None
        from datetime import UTC, datetime, timedelta

        return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    return None


def collect_repository_gmail_links(config: dict, *, repository) -> list[dict]:
    cutoff = gmail_query_cutoff(config["gmail"]["query_time_window"])
    stories = repository.list_stories(
        source_type="gmail",
        published_after=cutoff,
        include_paywalled=False,
        require_summary=True,
    )
    links = []
    for story in stories:
        source_name = normalize_gmail_source_name(str(story.get("source_name", "")).strip())
        links.append(
            {
                "subject": str(story.get("subject", "")).strip(),
                "from": source_name or "gmail",
                "source_name": source_name or "gmail",
                "source_type": "gmail",
                "date": str(story.get("email_sent_at", "") or story.get("published_at", "")).strip(),
                "email_sent_at": str(story.get("email_sent_at", "") or "").strip(),
                "published_at": str(story.get("published_at", "")).strip(),
                "url": str(story.get("url", "")).strip(),
                "anchor_text": str(story.get("anchor_text", "")).strip(),
                "context": str(story.get("context", "")).strip(),
                "category": str(story.get("category", "")).strip(),
                "summary": str(story.get("summary", "")).strip(),
                "article_text": str(story.get("article_text", "") or ""),
                "summary_raw": str(story.get("summary_raw", "") or ""),
                "summary_headline": str(story.get("summary_headline", "") or ""),
                "summary_body": str(story.get("summary_body", "") or ""),
            }
        )
    return links


def send_email(
    service,
    to_address: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    *,
    message_id_header: str = "",
    attachments: list[dict] | None = None,
) -> None:
    message = EmailMessage()
    message["To"] = to_address
    message["Subject"] = subject
    normalized_message_id = normalize_message_id_header(message_id_header)
    if normalized_message_id:
        message["Message-ID"] = normalized_message_id
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    for attachment in attachments or []:
        mime_type = str(attachment.get("mime_type", "application/octet-stream") or "application/octet-stream")
        maintype, _, subtype = mime_type.partition("/")
        content_bytes = attachment.get("content_bytes", b"")
        if isinstance(content_bytes, str):
            content_bytes = content_bytes.encode("utf-8")
        filename = str(attachment.get("filename", "attachment.bin") or "attachment.bin")
        message.add_attachment(
            bytes(content_bytes),
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=filename,
        )
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    service.users().messages().send(userId="me", body={"raw": encoded_message}).execute()


def send_email_to_recipients(
    service, recipients: list[str], subject: str, body: str
) -> None:
    for recipient in recipients:
        send_email(service, recipient, subject, body)
