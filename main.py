import base64
from collections import Counter
import html
import json
import os
import re
import subprocess
import traceback
from email.message import EmailMessage
from threading import Lock
from typing import Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from openai import OpenAI
import requests
import yaml

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
CONFIG_PATH = os.getenv("NEWSLETTER_CONFIG", "config.yaml")
DIGEST_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "templates", "digest.html"
)
DEFAULT_CONFIG = {
    "gmail": {"label": "Newsletters", "query_time_window": "newer_than:1d"},
    "paths": {"credentials": "secrets/credentials.json", "token": "secrets/token.json"},
    "additional_sources": {
        "enabled": False,
        "script_path": "skills/daily-news-curator/scripts/build_daily_digest.py",
        "feeds_file": "",
        "hours": 24,
        "top_per_category": 5,
        "max_total": 20,
    },
    "openai": {"reasoning_model": "gpt-4o-mini", "summary_model": "gpt-5-mini"},
    "limits": {
        "max_links_per_email": 15,
        "select_top_stories": 20,
        "max_per_category": 3,
        "final_top_stories": 15,
        "source_quotas": {"gmail": 10, "additional_source": 5},
        "max_article_chars": 6000,
        "max_summary_workers": 5,
    },
    "email": {
        "digest_recipients": ["zeizyy@gmail.com", "maisongting@gmail.com"],
        "digest_subject": "Daily Newsletter Digest",
        "alert_recipient": "zeizyy@gmail.com",
        "alert_subject_prefix": "[ALERT] Newsletter Curator Failure",
    },
}


def merge_dicts(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return merge_dicts(DEFAULT_CONFIG, data)


def load_credentials(paths: dict) -> Credentials:
    token_path = paths["token"]
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
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


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def trim_context(text: str, max_len: int = 240) -> str:
    text = normalize_whitespace(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def is_non_article_link(url: str, anchor_text: str, context: str) -> bool:
    lowered = " ".join([url, anchor_text, context]).lower()
    if url.startswith(("mailto:", "tel:", "sms:", "javascript:")):
        return True
    if url.startswith("#"):
        return True
    parsed = urlparse(url)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return True
    if not anchor_text and not context:
        return True
    if not anchor_text and context and len(context) < 20:
        return True
    if anchor_text and len(anchor_text) <= 2 and len(context) < 30:
        return True

    if any(
        token in parsed.path.lower()
        for token in [
            "/manage/",
            "/preferences",
            "/preference",
            "/subscribe",
            "/subscription",
            "/unsubscribe",
            "/signup",
            "/sign-up",
            "/login",
            "/account",
            "/member",
            "/privacy",
            "/terms",
            "/events",
            "/event",
            "/webinar",
        ]
    ):
        return True
    if any(
        token in lowered
        for token in [
            "unsubscribe",
            "subscription",
            "subscribe",
            "sign up",
            "signup",
            "preferences",
            "manage your",
            "manage preferences",
            "privacy policy",
            "terms",
            "sponsored",
            "sponsor",
            "advertise",
            "advertisement",
            "view in browser",
            "view online",
            "email preferences",
            "forward to a friend",
            "message from",
            "sponsored by",
            "presented by",
            "join now",
            "register",
            "follow us",
            "share this",
        ]
    ):
        return True
    return False


def extract_links_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href in seen:
            continue
        seen.add(href)
        anchor_text = anchor.get_text(" ", strip=True)
        parent_text = anchor.find_parent().get_text(" ", strip=True) if anchor.parent else ""
        context = trim_context(parent_text or anchor_text)
        if is_non_article_link(href, anchor_text, context):
            continue
        links.append(
            {
                "url": href,
                "anchor_text": anchor_text,
                "context": context,
            }
        )
    return links


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


def format_links_for_llm(items: list[dict]) -> str:
    lines = []
    for idx, item in enumerate(items, start=1):
        anchor_text = item.get("anchor_text", "")
        context = item.get("context", "")
        label = context or anchor_text
        lines.append(
            "\n".join(
                [
                    f"[{idx}] {label}".strip(),
                ]
            )
        )
    return "\n\n".join(lines)


def parse_index_list(text: str) -> list[int]:
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [int(x) for x in data if isinstance(x, (int, float, str)) and str(x).isdigit()]
    except json.JSONDecodeError:
        pass

    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, list):
                return [int(x) for x in data if isinstance(x, (int, float, str)) and str(x).isdigit()]
        except json.JSONDecodeError:
            return []
    return []


def parse_selection_items(text: str) -> list[dict]:
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass

    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except json.JSONDecodeError:
            return []
    return []


def select_top_stories(
    items: list[dict],
    usage_by_model: dict,
    top_stories: int,
    reasoning_model: str,
) -> list[dict]:
    if not items:
        return []

    client = OpenAI()
    system_prompt = (
        "You are a newsletter curator. Rank stories strictly by this priority order: "
        "Markets/stocks/macro/economy > Tech company news & strategy > AI & ML industry "
        "developments > Tech blogs > Interesting datapoints & anomalies. If two stories are "
        "from different tiers, always rank the higher-tier story above the lower-tier story, "
        "regardless of popularity. Within the same tier, score by relevance to these interests, "
        "timeliness, impact, and depth of insight. Penalize repetition, clickbait, or low-signal "
        "items. After scoring, enforce category diversity so the top selections include coverage "
        "across tech companies, AI/ML, macro/markets, deeper blogs/papers, and interesting "
        "datapoints. Exclude promos, subscriptions, and non-article links."
    )
    user_prompt = (
        "Here are extracted links with context. Select the top stories.\n"
        f"Return ONLY a JSON array of up to {top_stories} objects in ranked order.\n"
        "Score each story equally across timeliness, impact, and depth of insight; "
        "provide a final average score from 1-10.\n"
        "Each object must be: {\"index\": <int>, \"category\": <string>, "
        "\"score\": <number>, \"rationale\": <string>} "
        "where category is "
        "one of: Markets / stocks / macro / economy; Tech company news & strategy; "
        "AI & ML industry developments; Tech blogs; Interesting datapoints & anomalies.\n"
        "The \"index\" must refer to the numbered items in the input list below. Do NOT "
        "preserve input order; reorder by your ranking.\n"
        "No comments, no extra text, no trailing commas.\n\n"
        f"{format_links_for_llm(items)}"
    )
    response = client.chat.completions.create(
        model=reasoning_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    usage = response.usage
    if usage:
        stats = usage_by_model.setdefault(
            reasoning_model, {"input": 0, "output": 0, "total": 0}
        )
        stats["input"] += usage.prompt_tokens or 0
        stats["output"] += usage.completion_tokens or 0
        stats["total"] += usage.total_tokens or 0
    content = response.choices[0].message.content.strip()
    selections = parse_selection_items(content)
    if not selections:
        return []

    max_index = len(items)
    deduped = []
    seen = set()
    for selection in selections:
        idx = selection.get("index")
        if isinstance(idx, (int, float)) and int(idx) == idx:
            idx = int(idx)
        if isinstance(idx, int) and 1 <= idx <= max_index and idx not in seen:
            item = dict(items[idx - 1])
            item["category"] = selection.get("category", "")
            item["score"] = selection.get("score", "")
            item["rationale"] = selection.get("rationale", "")
            deduped.append(item)
            seen.add(idx)
        if len(deduped) >= top_stories:
            break
    return deduped


def fetch_article_text(
    url: str,
    max_article_chars: int,
    timeout: int = 25,
    retries: int = 3,
) -> str:
    try:
        last_exc = None
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (newsletter-curator)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/",
            "Connection": "keep-alive",
        }
        for attempt in range(1, retries + 1):
            try:
                response = session.get(url, headers=headers, timeout=timeout)
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < retries:
                    continue
                raise last_exc
        if response is None:
            return ""
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        article = soup.find("article")
        text = article.get_text(" ", strip=True) if article else soup.get_text(" ", strip=True)
        text = normalize_whitespace(text)
        return text[:max_article_chars]
    except requests.RequestException as exc:
        print(f"Failed to fetch article: {url} ({exc})")
        return ""


def summarize_article_with_llm(
    article_text: str,
    usage_by_model: dict,
    lock: Lock,
    summary_model: str,
) -> str:
    if not article_text:
        return "No article text available."

    client = OpenAI()
    system_prompt = (
        "You are a concise financial/tech news analyst writing for a specific reader "
        "with priorities: Markets/stocks/macro/economy > Tech company news & strategy > "
        "AI & ML industry developments > Tech blogs > Interesting datapoints & anomalies."
    )
    user_prompt = (
        "Write ~300 words on the article below.\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\"headline\": <string>, \"body\": <string>}.\n"
        "The body should include:\n"
        "1) Key takeaways (3-5 bullets).\n"
        "2) Why this matters to me (1 paragraph).\n"
        "No extra text.\n\n"
        f"Article text:\n{article_text}"
    )
    response = client.chat.completions.create(
        model=summary_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    usage = response.usage
    if usage:
        with lock:
            stats = usage_by_model.setdefault(
                summary_model, {"input": 0, "output": 0, "total": 0}
            )
            stats["input"] += usage.prompt_tokens or 0
            stats["output"] += usage.completion_tokens or 0
            stats["total"] += usage.total_tokens or 0
    return response.choices[0].message.content.strip()


def process_story(
    item: dict,
    usage_by_model: dict,
    lock: Lock,
    max_article_chars: int,
    summary_model: str,
) -> str | None:
    article_text = fetch_article_text(item.get("url", ""), max_article_chars)
    if not article_text:
        return None
    summary = summarize_article_with_llm(article_text, usage_by_model, lock, summary_model)
    headline, body = extract_summary_json(summary)
    if not body.strip() or body.strip() == "No article text available.":
        return None
    summary_block = "\n\n".join(
        [
            f"Story: {headline}",
            f"URL: {item.get('url', '')}",
            body,
        ]
    )
    return summary_block


def post_process_selected(
    items: list[dict],
    max_per_category: int,
    total_limit: int,
    source_quotas: dict[str, int] | None = None,
) -> list[dict]:
    if not items:
        return []

    category_counts = {}
    source_counts = {}
    result = []
    for item in items:
        category = item.get("category", "") or "Uncategorized"
        source_type = item.get("source_type", "") or "unknown"
        if category_counts.get(category, 0) >= max_per_category:
            continue
        if source_quotas:
            quota = source_quotas.get(source_type)
            if quota is not None and source_counts.get(source_type, 0) >= quota:
                continue
        result.append(item)
        category_counts[category] = category_counts.get(category, 0) + 1
        source_counts[source_type] = source_counts.get(source_type, 0) + 1
        if len(result) >= total_limit:
            break

    # Optional fallback for non-quota sources (or if quotas are not configured).
    if len(result) < total_limit and source_quotas:
        selected_urls = {item.get("url", "") for item in result}
        for item in items:
            url = item.get("url", "")
            if url in selected_urls:
                continue
            category = item.get("category", "") or "Uncategorized"
            source_type = item.get("source_type", "") or "unknown"
            if source_type in source_quotas:
                continue
            if category_counts.get(category, 0) >= max_per_category:
                continue
            result.append(item)
            selected_urls.add(url)
            category_counts[category] = category_counts.get(category, 0) + 1
            source_counts[source_type] = source_counts.get(source_type, 0) + 1
            if len(result) >= total_limit:
                break
    elif len(result) < total_limit:
        # Preserve previous behavior when no source quota config is provided.
        selected_urls = {item.get("url", "") for item in result}
        for item in items:
            url = item.get("url", "")
            if url in selected_urls:
                continue
            category = item.get("category", "") or "Uncategorized"
            if category_counts.get(category, 0) >= max_per_category:
                continue
            result.append(item)
            selected_urls.add(url)
            category_counts[category] = category_counts.get(category, 0) + 1
            source_type = item.get("source_type", "") or "unknown"
            source_counts[source_type] = source_counts.get(source_type, 0) + 1
            if len(result) >= total_limit:
                break
    return result


def normalize_source_quotas(raw: dict | None) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    normalized = {}
    for source_name, quota in raw.items():
        if not isinstance(source_name, str):
            continue
        if isinstance(quota, (int, float)) and int(quota) == quota and int(quota) >= 0:
            normalized[source_name.strip()] = int(quota)
    return normalized


def extract_summary_json(summary: str) -> tuple[str, str]:
    try:
        data = json.loads(summary)
        if isinstance(data, dict):
            headline = data.get("headline", "").strip() or "Untitled"
            body = data.get("body", "").strip()
            return headline, body or summary
    except json.JSONDecodeError:
        pass
    return "Untitled", summary


def group_summaries_by_category(summaries: list[tuple[int, dict, str]]) -> dict:
    grouped = {}
    for _, item, summary in summaries:
        category = item.get("category", "") or "Uncategorized"
        grouped.setdefault(category, []).append(summary)
    return grouped


def parse_summary_block(summary_block: str) -> tuple[str, str, str]:
    chunks = summary_block.split("\n\n", 2)
    title_line = chunks[0] if chunks else ""
    url_line = chunks[1] if len(chunks) > 1 else ""
    body = chunks[2] if len(chunks) > 2 else summary_block

    title = title_line
    if ":" in title_line:
        title = title_line.split(":", 1)[1].strip() or title_line
    url = url_line.replace("URL:", "", 1).strip() if url_line.startswith("URL:") else ""
    return title, url, body


def render_summary_body_html(body: str) -> str:
    lines = body.splitlines()
    blocks = []
    list_items = []

    def flush_list() -> None:
        nonlocal list_items
        if not list_items:
            return
        items_html = "".join(
            (
                '<li class="summary-list-item" style="margin:0 0 6px 0;">'
                f"{html.escape(item)}"
                "</li>"
            )
            for item in list_items
        )
        blocks.append(
            (
                '<ul class="summary-list" style="margin:8px 0 12px 20px;padding:0;color:#25364d;line-height:1.55;">'
                f"{items_html}"
                "</ul>"
            )
        )
        list_items = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_list()
            continue

        list_match = re.match(r"^[-*]\s+(.+)$", line)
        if list_match:
            list_items.append(list_match.group(1))
            continue

        flush_list()

        markdown_heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        section_heading = re.match(r"^\d+[.)]\s+(.+)$", line)
        if markdown_heading or section_heading:
            heading_text = (
                markdown_heading.group(2) if markdown_heading else section_heading.group(1)
            )
            blocks.append(
                (
                    '<div class="summary-heading" style="font-size:15px;font-weight:700;line-height:1.35;'
                    'color:#152238;margin:12px 0 6px 0;">'
                    f"{html.escape(heading_text)}"
                    "</div>"
                )
            )
            continue

        blocks.append(
            (
                '<p class="summary-paragraph" style="margin:0 0 10px 0;color:#25364d;line-height:1.6;">'
                f"{html.escape(line)}"
                "</p>"
            )
        )

    flush_list()
    return "".join(blocks) or "No summary."


def render_digest_html(grouped: dict[str, list[str]]) -> str:
    category_sections = []
    for category, entries in grouped.items():
        cards = []
        for summary_block in entries:
            title, url, body = parse_summary_block(summary_block)
            body_html = render_summary_body_html(body)
            link_html = (
                f'<a href="{html.escape(url)}" class="story-link" style="color:#0b57d0;text-decoration:none;">Read article</a>'
                if url
                else ""
            )
            cards.append(
                (
                    '<div class="story-card" style="background:#ffffff;border:1px solid #e6ecf5;border-radius:12px;'
                    'padding:16px;margin:0 0 12px 0;">'
                    f'<div class="story-title" style="font-size:20px;font-weight:700;line-height:1.35;color:#152238;margin:0 0 8px 0;">{html.escape(title)}</div>'
                    f'<div class="story-body" style="font-size:14px;line-height:1.6;color:#25364d;margin:0 0 10px 0;">{body_html}</div>'
                    f'<div class="story-cta" style="font-size:14px;font-weight:600;">{link_html}</div>'
                    "</div>"
                )
            )
        category_sections.append(
            (
                '<div class="category-section" style="margin:0 0 20px 0;">'
                f'<div class="category-title" style="font-size:22px;font-weight:700;line-height:1.3;color:#243b5a;'
                f'margin:0 0 10px 0;">{html.escape(category)}</div>'
                f"{''.join(cards)}"
                "</div>"
            )
        )

    with open(DIGEST_TEMPLATE_PATH, "r", encoding="utf-8") as handle:
        template_html = handle.read()
    return template_html.replace("{{CATEGORY_SECTIONS}}", "".join(category_sections))


def collect_additional_source_links(config: dict) -> list[dict]:
    source_cfg = config.get("additional_sources", {})
    if not source_cfg.get("enabled", False):
        return []

    script_path = source_cfg.get(
        "script_path", "skills/daily-news-curator/scripts/build_daily_digest.py"
    )
    if not os.path.isabs(script_path):
        script_path = os.path.join(os.path.dirname(__file__), script_path)
    if not os.path.exists(script_path):
        print(f"Additional sources script not found: {script_path}")
        return []

    command = [
        "python3",
        script_path,
        "--output",
        "json",
        "--hours",
        str(source_cfg.get("hours", 24)),
        "--top-per-category",
        str(source_cfg.get("top_per_category", 5)),
        "--max-total",
        str(source_cfg.get("max_total", 20)),
    ]

    feeds_file = source_cfg.get("feeds_file", "")
    if feeds_file:
        if not os.path.isabs(feeds_file):
            feeds_file = os.path.join(os.path.dirname(__file__), feeds_file)
        command.extend(["--feeds-file", feeds_file])

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print("Additional source ingestion failed.")
        if result.stderr.strip():
            print(result.stderr.strip())
        return []

    output = result.stdout.strip()
    if not output:
        return []

    try:
        stories = json.loads(output)
    except json.JSONDecodeError:
        print("Additional source ingestion returned non-JSON output.")
        return []

    if not isinstance(stories, list):
        print("Additional source ingestion output was not a list.")
        return []

    links = []
    for story in stories:
        if not isinstance(story, dict):
            continue
        url = str(story.get("url", "")).strip()
        if not url:
            continue
        title = str(story.get("title", "")).strip()
        source = str(story.get("source", "")).strip() or "Additional Source"
        category = str(story.get("category", "")).strip()
        published_at = str(story.get("published_at", "")).strip()
        summary = str(story.get("summary", "")).strip()
        context = trim_context(summary or title or url)
        links.append(
            {
                "subject": f"[{category or 'general'}] {title or source}",
                "from": source,
                "source_name": source,
                "source_type": "additional_source",
                "date": published_at,
                "url": url,
                "anchor_text": title or source,
                "context": context,
            }
        )
    return links


def dedupe_links_by_url(items: list[dict]) -> list[dict]:
    deduped = []
    seen = set()
    for item in items:
        url = str(item.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(item)
    return deduped


def format_counts(
    items: list[dict], field: str, top_n: int | None = None, missing_label: str = "unknown"
) -> str:
    counts = Counter((str(item.get(field, "")).strip() or missing_label) for item in items)
    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    if top_n is not None:
        ordered = ordered[:top_n]
    return ", ".join(f"{name}={count}" for name, count in ordered) if ordered else "none"


def run_job(config: dict, service) -> None:
    gmail_cfg = config["gmail"]
    openai_cfg = config["openai"]
    limits_cfg = config["limits"]
    email_cfg = config["email"]

    query = gmail_cfg["query_time_window"]
    label_id = get_label_id(service, gmail_cfg["label"])
    message_ids = list_message_ids_for_label(service, label_id, query)
    print(f"Found {len(message_ids)} messages for query: {query}")

    all_links = []
    for message_id in message_ids:
        message = get_message(service, message_id)
        payload = message.get("payload", {})
        headers = payload.get("headers", [])
        subject = get_header_value(headers, "Subject")
        from_header = get_header_value(headers, "From")
        date_header = get_header_value(headers, "Date")

        text_bodies, html_bodies = extract_bodies(payload)
        links = []
        for html in html_bodies:
            links.extend(extract_links_from_html(html))
        links = links[: limits_cfg["max_links_per_email"]]
        for link in links:
            all_links.append(
                {
                    "subject": subject,
                    "from": from_header,
                    "source_name": from_header or "gmail",
                    "source_type": "gmail",
                    "date": date_header,
                    "url": link["url"],
                    "anchor_text": link["anchor_text"],
                    "context": link["context"],
                }
            )

    gmail_links_count = len(all_links)
    source_links = collect_additional_source_links(config)
    all_links.extend(source_links)
    all_links = dedupe_links_by_url(all_links)
    print("\n=== Pipeline Stats ===")
    print(f"messages_retrieved: {len(message_ids)}")
    print(
        f"links_retrieved: gmail={gmail_links_count}, additional_sources={len(source_links)}"
    )
    print(f"links_merged_deduped: total={len(all_links)}")
    print(
        f"links_by_source_type: {format_counts(all_links, 'source_type')}"
    )
    print(
        f"links_by_source_name_top10: {format_counts(all_links, 'source_name', top_n=10)}"
    )
    usage_by_model = {}
    ranked_candidates = select_top_stories(
        all_links,
        usage_by_model,
        limits_cfg["select_top_stories"],
        openai_cfg["reasoning_model"],
    )
    if not ranked_candidates:
        print("No top stories selected.")
        return

    print(f"ranked_selected: total={len(ranked_candidates)}")
    print(
        f"ranked_by_source_type: {format_counts(ranked_candidates, 'source_type')}"
    )
    print(
        f"ranked_by_source_name_top10: {format_counts(ranked_candidates, 'source_name', top_n=10)}"
    )

    selected = post_process_selected(
        ranked_candidates,
        limits_cfg["max_per_category"],
        limits_cfg["final_top_stories"],
        normalize_source_quotas(limits_cfg.get("source_quotas")),
    )
    if not selected:
        print("No stories selected after category caps.")
        return

    target_story_count = len(selected)
    selected_urls = {item.get("url", "") for item in selected}
    fallback_candidates = [
        item for item in ranked_candidates if item.get("url", "") not in selected_urls
    ]
    backfilled_count = 0
    skipped_count = 0
    accepted_items = []
    summaries = []
    lock = Lock()
    for item in selected:
        summary_block = process_story(
            item,
            usage_by_model,
            lock,
            limits_cfg["max_article_chars"],
            openai_cfg["summary_model"],
        )
        if summary_block:
            accepted_items.append(item)
            summaries.append((len(accepted_items), item, summary_block))
            continue

        skipped_count += 1
        replacement_summary = None
        replacement_item = None
        while fallback_candidates and replacement_summary is None:
            candidate = fallback_candidates.pop(0)
            candidate_summary = process_story(
                candidate,
                usage_by_model,
                lock,
                limits_cfg["max_article_chars"],
                openai_cfg["summary_model"],
            )
            if candidate_summary:
                replacement_summary = candidate_summary
                replacement_item = candidate
            else:
                skipped_count += 1

        if replacement_summary and replacement_item:
            backfilled_count += 1
            accepted_items.append(replacement_item)
            summaries.append((len(accepted_items), replacement_item, replacement_summary))

    print(f"summaries_completed: total={len(accepted_items)} target={target_story_count}")
    print(f"summaries_backfilled: {backfilled_count}")
    print(f"summaries_skipped_fetch_or_empty: {skipped_count}")
    if not summaries:
        print("No stories could be summarized after fetch/filter checks.")
        return

    print(f"returned_final: total={len(accepted_items)}")
    print(f"final_by_source_type: {format_counts(accepted_items, 'source_type')}")
    print(
        f"final_by_source_name_top10: {format_counts(accepted_items, 'source_name', top_n=10)}"
    )

    grouped = group_summaries_by_category(summaries)
    sections = []
    for category, entries in grouped.items():
        section_text = [category, ""]
        section_text.extend(entries)
        sections.append("\n\n".join(section_text))
    final_text = "\n\n===\n\n".join(sections)

    if usage_by_model:
        print("\n=== Token Usage ===")
        for model_name, stats in usage_by_model.items():
            print(
                f"{model_name}: input={stats['input']} output={stats['output']} total={stats['total']}"
            )

    digest_html = render_digest_html(grouped)
    for recipient in email_cfg["digest_recipients"]:
        send_email(
            service,
            to_address=recipient,
            subject=email_cfg["digest_subject"],
            body=final_text,
            html_body=digest_html,
        )


def main():
    config = load_config()
    service = None
    try:
        service = get_gmail_service(config["paths"])
        run_job(config, service)
    except Exception:
        error_details = traceback.format_exc()
        print(error_details)
        if service:
            try:
                send_email(
                    service,
                    to_address=config["email"]["alert_recipient"],
                    subject=f"{config['email']['alert_subject_prefix']}",
                    body=error_details,
                )
            except Exception as exc:
                print(f"Failed to send alert email: {exc}")
        raise


if __name__ == "__main__":
    main()
