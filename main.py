import base64
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
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

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
CREDENTIALS_PATH = "secrets/credentials.json"
TOKEN_PATH = "secrets/token.json"
NEWSLETTER_LABEL = "Newsletters"
QUERY_TIME_WINDOW = "newer_than:1d"
MAX_LINKS_PER_EMAIL = 15
OPENAI_REASONING_MODEL = os.getenv("OPENAI_REASONING_MODEL", "gpt-4o-mini")
OPENAI_SUMMARY_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5-mini")
TOP_STORIES = 2 # lower for testing. remember to increase back to 15
MAX_ARTICLE_CHARS = 6000
MAX_SUMMARY_WORKERS = 5


def load_credentials() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())
    return creds


def get_gmail_service():
    creds = load_credentials()
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


def send_email(service, to_address: str, subject: str, body: str) -> None:
    message_text = "\n".join(
        [
            f"To: {to_address}",
            f"Subject: {subject}",
            "Content-Type: text/plain; charset=utf-8",
            "",
            body,
        ]
    )
    encoded_message = base64.urlsafe_b64encode(message_text.encode("utf-8")).decode("utf-8")
    service.users().messages().send(userId="me", body={"raw": encoded_message}).execute()


def format_links_for_llm(items: list[dict]) -> str:
    lines = []
    for idx, item in enumerate(items, start=1):
        anchor_text = item.get("anchor_text", "")
        context = item.get("context", "")
        lines.append(
            "\n".join(
                [
                    f"[{idx}] {anchor_text}".strip(),
                    f"Context: {context}",
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


def select_top_stories(items: list[dict], usage_by_model: dict) -> list[dict]:
    if not items:
        return []

    client = OpenAI()
    system_prompt = (
        "You are a newsletter curator. Rank the most important stories based on the user's "
        "priority: Markets/stocks/macro/economy > Tech company news & strategy > AI & ML "
        "industry developments > Tech blogs > Interesting datapoints & anomalies. Focus on "
        "substantive stories and avoid promos, subscriptions, and non-article links."
    )
    user_prompt = (
        "Here are extracted links with context. Select the top stories.\n"
        f"Return a JSON array of up to {TOP_STORIES} item indices in ranked order.\n\n"
        f"{format_links_for_llm(items)}"
    )
    print("\n=== LLM Prompt (System) ===")
    print(system_prompt)
    print("\n=== LLM Prompt (User) ===")
    print(user_prompt)
    response = client.chat.completions.create(
        model=OPENAI_REASONING_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    usage = response.usage
    if usage:
        stats = usage_by_model.setdefault(
            OPENAI_REASONING_MODEL, {"input": 0, "output": 0, "total": 0}
        )
        stats["input"] += usage.prompt_tokens or 0
        stats["output"] += usage.completion_tokens or 0
        stats["total"] += usage.total_tokens or 0
    content = response.choices[0].message.content.strip()
    indices = parse_index_list(content)
    if not indices:
        return []

    max_index = len(items)
    deduped = []
    seen = set()
    for idx in indices:
        if 1 <= idx <= max_index and idx not in seen:
            deduped.append(idx)
            seen.add(idx)
        if len(deduped) >= TOP_STORIES:
            break
    return [items[i - 1] for i in deduped]


def fetch_article_text(url: str) -> str:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (newsletter-curator)"},
            timeout=15,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        article = soup.find("article")
        text = article.get_text(" ", strip=True) if article else soup.get_text(" ", strip=True)
        text = normalize_whitespace(text)
        return text[:MAX_ARTICLE_CHARS]
    except requests.RequestException as exc:
        print(f"Failed to fetch article: {url} ({exc})")
        return ""


def summarize_article_with_llm(article_text: str, usage_by_model: dict, lock: Lock) -> str:
    if not article_text:
        return "No article text available."

    client = OpenAI()
    system_prompt = (
        "You are a concise financial/tech news analyst writing for a specific reader "
        "with priorities: Markets/stocks/macro/economy > Tech company news & strategy > "
        "AI & ML industry developments > Tech blogs > Interesting datapoints & anomalies."
    )
    user_prompt = (
        "Write ~300 words on the article below. Include:\n"
        "1) A short headline.\n"
        "2) Key takeaways (3-5 bullets).\n"
        "3) Why this matters to me (1 paragraph).\n\n"
        f"Article text:\n{article_text}"
    )
    print("\n=== LLM Prompt (System) ===")
    print(system_prompt)
    print("\n=== LLM Prompt (User) ===")
    print(user_prompt)
    response = client.chat.completions.create(
        model=OPENAI_SUMMARY_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    usage = response.usage
    if usage:
        with lock:
            stats = usage_by_model.setdefault(
                OPENAI_SUMMARY_MODEL, {"input": 0, "output": 0, "total": 0}
            )
            stats["input"] += usage.prompt_tokens or 0
            stats["output"] += usage.completion_tokens or 0
            stats["total"] += usage.total_tokens or 0
    return response.choices[0].message.content.strip()


def process_story(
    idx: int, item: dict, usage_by_model: dict, lock: Lock
) -> tuple[int, str]:
    article_text = fetch_article_text(item.get("url", ""))
    summary = summarize_article_with_llm(article_text, usage_by_model, lock)
    summary_block = "\n".join(
        [
            f"Story {idx}: {item.get('anchor_text', '')}",
            f"URL: {item.get('url', '')}",
            summary,
        ]
    )
    return idx, summary_block

def main():
    service = get_gmail_service()
    query = QUERY_TIME_WINDOW
    label_id = get_label_id(service, NEWSLETTER_LABEL)
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
        links = links[:MAX_LINKS_PER_EMAIL]
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
            print(f"- {link['anchor_text']}: {link['url']}")
            print(f"  Context: {link['context']}")

    print("\n=== Curated Digest ===")
    usage_by_model = {}
    selected = select_top_stories(all_links, usage_by_model)
    if not selected:
        print("No top stories selected.")
        return

    summaries = []
    lock = Lock()
    with ThreadPoolExecutor(max_workers=MAX_SUMMARY_WORKERS) as executor:
        futures = [
            executor.submit(process_story, idx, item, usage_by_model, lock)
            for idx, item in enumerate(selected, start=1)
        ]
        for future in as_completed(futures):
            summaries.append(future.result())

    summaries.sort(key=lambda item: item[0])
    final_text = "\n\n---\n\n".join(summary for _, summary in summaries)
    print(final_text)

    if usage_by_model:
        print("\n=== Token Usage ===")
        for model_name, stats in usage_by_model.items():
            print(
                f"{model_name}: input={stats['input']} output={stats['output']} total={stats['total']}"
            )

    send_email(
        service,
        to_address="zeizyy@gmail.com",
        subject="Daily Newsletter Digest",
        body=final_text,
    )


if __name__ == "__main__":
    main()
