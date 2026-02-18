import base64
import html
import json
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
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
DEFAULT_CONFIG = {
    "gmail": {"label": "Newsletters", "query_time_window": "newer_than:1d"},
    "paths": {"credentials": "secrets/credentials.json", "token": "secrets/token.json"},
    "openai": {"reasoning_model": "gpt-4o-mini", "summary_model": "gpt-5-mini"},
    "limits": {
        "max_links_per_email": 15,
        "select_top_stories": 20,
        "max_per_category": 3,
        "final_top_stories": 10,
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
    print("\n=== LLM Prompt (System) ===")
    print(system_prompt)
    print("\n=== LLM Prompt (User) ===")
    print(user_prompt)
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
    print("\n=== LLM Raw Output (Selection) ===")
    print(content)
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
    print("\n=== LLM Prompt (System) ===")
    print(system_prompt)
    print("\n=== LLM Prompt (User) ===")
    print(user_prompt)
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
    idx: int,
    item: dict,
    usage_by_model: dict,
    lock: Lock,
    max_article_chars: int,
    summary_model: str,
) -> tuple[int, str]:
    article_text = fetch_article_text(item.get("url", ""), max_article_chars)
    summary = summarize_article_with_llm(article_text, usage_by_model, lock, summary_model)
    headline, body = extract_summary_json(summary)
    summary_block = "\n\n".join(
        [
            f"Story {idx}: {headline}",
            f"URL: {item.get('url', '')}",
            body,
        ]
    )
    return idx, summary_block


def post_process_selected(
    items: list[dict], max_per_category: int, total_limit: int
) -> list[dict]:
    if not items:
        return []

    counts = {}
    result = []
    for item in items:
        category = item.get("category", "") or "Uncategorized"
        if counts.get(category, 0) >= max_per_category:
            continue
        result.append(item)
        counts[category] = counts.get(category, 0) + 1
        if len(result) >= total_limit:
            break
    return result


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


def render_digest_html(grouped: dict[str, list[str]]) -> str:
    category_sections = []
    for category, entries in grouped.items():
        cards = []
        for summary_block in entries:
            title, url, body = parse_summary_block(summary_block)
            body_html = "<br>".join(html.escape(line) for line in body.splitlines()) or "No summary."
            link_html = (
                f'<a href="{html.escape(url)}" style="color:#0b57d0;text-decoration:none;">Read article</a>'
                if url
                else ""
            )
            cards.append(
                (
                    '<div style="background:#ffffff;border:1px solid #e6ecf5;border-radius:12px;'
                    'padding:16px;margin:0 0 12px 0;">'
                    f'<div style="font-size:18px;font-weight:700;color:#152238;margin:0 0 8px 0;">{html.escape(title)}</div>'
                    f'<div style="font-size:14px;line-height:1.6;color:#25364d;margin:0 0 10px 0;">{body_html}</div>'
                    f'<div style="font-size:14px;font-weight:600;">{link_html}</div>'
                    "</div>"
                )
            )
        category_sections.append(
            (
                '<div style="margin:0 0 20px 0;">'
                f'<div style="font-size:13px;font-weight:700;letter-spacing:0.08em;color:#4d5f78;'
                f'text-transform:uppercase;margin:0 0 10px 0;">{html.escape(category)}</div>'
                f"{''.join(cards)}"
                "</div>"
            )
        )

    return (
        '<html><body style="margin:0;padding:0;background:#f4f7fb;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;">'
        '<div style="max-width:760px;margin:0 auto;padding:28px 16px;">'
        '<div style="background:linear-gradient(135deg,#0f2748,#1c4d8c);border-radius:14px;padding:20px 22px;'
        'color:#ffffff;margin:0 0 18px 0;">'
        '<div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;opacity:0.9;">Daily Briefing</div>'
        '<div style="font-size:28px;font-weight:750;line-height:1.2;margin:6px 0 0 0;">Newsletter Digest</div>'
        "</div>"
        f"{''.join(category_sections)}"
        '<div style="font-size:12px;color:#73859f;margin-top:8px;">Generated by Newsletter Curator</div>'
        "</div></body></html>"
    )

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
                    "date": date_header,
                    "url": link["url"],
                    "anchor_text": link["anchor_text"],
                    "context": link["context"],
                }
            )

        print("\n---")
        print(f"Subject: {subject}")
        print(f"From: {from_header}")
        print(f"Date: {date_header}")
        print(f"Links: {len(links)}")
        for link in links:
            print(f"- {link['context']}: {link['url']}")
            print(f"  Context: {link['context']}")
    print("\n=== Curated Digest ===")
    usage_by_model = {}
    selected = select_top_stories(
        all_links,
        usage_by_model,
        limits_cfg["select_top_stories"],
        openai_cfg["reasoning_model"],
    )
    if not selected:
        print("No top stories selected.")
        return

    print("\n=== Selected Stories (Pre-Cap) ===")
    for idx, item in enumerate(selected, start=1):
        print(f"{idx}. {item.get('context', '')}")
        print(f"   URL: {item.get('url', '')}")
        print(f"   Context: {item.get('context', '')}")
        print(f"   Category: {item.get('category', '')}")
        print(f"   Score: {item.get('score', '')}")
        print(f"   Rationale: {item.get('rationale', '')}")

    selected = post_process_selected(
        selected,
        limits_cfg["max_per_category"],
        limits_cfg["final_top_stories"],
    )
    if not selected:
        print("No stories selected after category caps.")
        return

    print("\n=== Selected Stories (Final) ===")
    for idx, item in enumerate(selected, start=1):
        print(f"{idx}. {item.get('context', '')}")
        print(f"   URL: {item.get('url', '')}")
        print(f"   Context: {item.get('context', '')}")
        print(f"   Category: {item.get('category', '')}")
        print(f"   Score: {item.get('score', '')}")
        print(f"   Rationale: {item.get('rationale', '')}")
    summaries = []
    lock = Lock()
    with ThreadPoolExecutor(max_workers=limits_cfg["max_summary_workers"]) as executor:
        futures = [
            executor.submit(
                process_story,
                idx,
                item,
                usage_by_model,
                lock,
                limits_cfg["max_article_chars"],
                openai_cfg["summary_model"],
            )
            for idx, item in enumerate(selected, start=1)
        ]
        for future in as_completed(futures):
            story_idx, summary_block = future.result()
            summaries.append((story_idx, selected[story_idx - 1], summary_block))

    summaries.sort(key=lambda item: item[0])
    grouped = group_summaries_by_category(summaries)
    sections = []
    for category, entries in grouped.items():
        section_text = [category, ""]
        section_text.extend(entries)
        sections.append("\n\n".join(section_text))
    final_text = "\n\n===\n\n".join(sections)
    print(final_text)

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
