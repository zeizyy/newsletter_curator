from __future__ import annotations

import base64
import email.utils
from email.message import EmailMessage
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

    all_links = []
    for message_id in message_ids:
        message = get_message_fn(service, message_id)
        payload = message.get("payload", {})
        headers = payload.get("headers", [])
        subject = get_header_value_fn(headers, "Subject")
        from_header = get_header_value_fn(headers, "From")
        date_header = get_header_value_fn(headers, "Date")

        _text_bodies, html_bodies = extract_bodies_fn(payload)
        links = []
        for html in html_bodies:
            links.extend(extract_links_from_html_fn(html))
        links = links[: limits_cfg["max_links_per_email"]]
        for link in links:
            all_links.append(
                {
                    "subject": subject,
                    "from": from_header,
                    "source_name": from_header or "gmail",
                    "source_type": "gmail",
                    "date": date_header,
                    "published_at": parse_email_datetime(date_header),
                    "url": link["url"],
                    "anchor_text": link["anchor_text"],
                    "context": link["context"],
                }
            )
    return all_links


def _gmail_query_cutoff(query: str) -> str | None:
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
    cutoff = _gmail_query_cutoff(config["gmail"]["query_time_window"])
    stories = repository.list_stories(source_type="gmail", published_after=cutoff)
    links = []
    for story in stories:
        links.append(
            {
                "subject": str(story.get("subject", "")).strip(),
                "from": str(story.get("source_name", "")).strip() or "gmail",
                "source_name": str(story.get("source_name", "")).strip() or "gmail",
                "source_type": "gmail",
                "date": str(story.get("published_at", "")).strip(),
                "published_at": str(story.get("published_at", "")).strip(),
                "url": str(story.get("url", "")).strip(),
                "anchor_text": str(story.get("anchor_text", "")).strip(),
                "context": str(story.get("context", "")).strip(),
                "category": str(story.get("category", "")).strip(),
                "summary": str(story.get("summary", "")).strip(),
                "article_text": str(story.get("article_text", "") or ""),
            }
        )
    return links


def send_email(
    service, to_address: str, subject: str, body: str, html_body: str | None = None
) -> None:
    message = EmailMessage()
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    service.users().messages().send(userId="me", body={"raw": encoded_message}).execute()


def send_email_to_recipients(
    service, recipients: list[str], subject: str, body: str
) -> None:
    for recipient in recipients:
        send_email(service, recipient, subject, body)
