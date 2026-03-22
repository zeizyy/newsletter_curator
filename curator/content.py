from __future__ import annotations

import json
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests
from trafilatura import extract


PAYWALL_STRONG_MARKERS = {
    "subscribe to continue reading": "subscribe_to_continue",
    "subscribe to read this article": "subscribe_to_read",
    "subscription required": "subscription_required",
    "this content is for subscribers": "subscribers_only",
    "already a subscriber": "already_a_subscriber",
    "sign in to continue reading": "sign_in_to_continue",
    "start your subscription": "start_subscription",
    "unlock this article": "unlock_article",
}

PAYWALL_WEAK_MARKERS = {
    "subscribe now": "subscribe_now",
    "continue reading": "continue_reading",
    "subscriber-only": "subscriber_only",
    "membership required": "membership_required",
    "join to read more": "join_to_read",
}

GENERIC_CTA_TITLES = {
    "read more",
    "continue reading",
    "learn more",
    "click here",
    "view story",
    "read the story",
    "full story",
    "details",
    "watch now",
}


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def trim_context(text: str, max_len: int = 240) -> str:
    text = normalize_whitespace(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def normalize_title_candidate(text: str) -> str:
    return normalize_whitespace(text).strip(" \t\r\n-:|>.,!?").lower()


def is_generic_title(text: str) -> bool:
    return normalize_title_candidate(text) in GENERIC_CTA_TITLES


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


def extract_article_details_from_html(
    html: str,
    *,
    url: str = "",
    max_article_chars: int = 6000,
) -> dict[str, str]:
    extracted = extract(
        html,
        url=url or None,
        output_format="json",
        with_metadata=True,
        include_comments=False,
        include_tables=False,
    )
    payload: dict[str, str] = {}
    if extracted:
        try:
            payload = json.loads(extracted)
        except json.JSONDecodeError:
            payload = {}

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = normalize_whitespace(str(payload.get("title", "") or ""))
    if not title:
        for selector in [
            ('meta[property="og:title"]', "content"),
            ('meta[name="twitter:title"]', "content"),
            ("title", None),
        ]:
            node = soup.select_one(selector[0])
            if not node:
                continue
            if selector[1]:
                title = normalize_whitespace(str(node.get(selector[1], "") or ""))
            else:
                title = normalize_whitespace(node.get_text(" ", strip=True))
            if title:
                break

    article_text = normalize_whitespace(str(payload.get("text", "") or payload.get("raw_text", "") or ""))
    if not article_text:
        article = soup.find("article")
        article_text = normalize_whitespace(
            article.get_text(" ", strip=True) if article else soup.get_text(" ", strip=True)
        )

    excerpt = normalize_whitespace(str(payload.get("excerpt", "") or ""))
    if not excerpt:
        excerpt = trim_context(article_text)

    return {
        "article_text": article_text[:max_article_chars],
        "document_title": title,
        "document_excerpt": excerpt,
    }


def fetch_article_details(
    url: str,
    max_article_chars: int,
    timeout: int = 25,
    retries: int = 3,
) -> dict[str, str]:
    try:
        last_exc = None
        response = None
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
            return {"article_text": "", "document_title": "", "document_excerpt": ""}
        return extract_article_details_from_html(
            response.text,
            url=url,
            max_article_chars=max_article_chars,
        )
    except requests.RequestException as exc:
        print(f"Failed to fetch article: {url} ({exc})")
        return {"article_text": "", "document_title": "", "document_excerpt": ""}


def fetch_article_text(
    url: str,
    max_article_chars: int,
    timeout: int = 25,
    retries: int = 3,
) -> str:
    details = fetch_article_details(
        url,
        max_article_chars=max_article_chars,
        timeout=timeout,
        retries=retries,
    )
    return details.get("article_text", "")


def detect_paywalled_article(article_text: str, url: str = "") -> tuple[bool, str]:
    text = normalize_whitespace(article_text).lower()
    if not text:
        return False, ""

    for marker, reason in PAYWALL_STRONG_MARKERS.items():
        if marker in text and len(text) <= 2500:
            return True, reason

    weak_hits = [reason for marker, reason in PAYWALL_WEAK_MARKERS.items() if marker in text]
    parsed = urlparse(url)
    paywallish_path = any(
        token in parsed.path.lower()
        for token in ["/subscribe", "/subscription", "/member", "/login", "/signin"]
    )
    if len(weak_hits) >= 2 and len(text) <= 1500:
        return True, weak_hits[0]
    if weak_hits and paywallish_path and len(text) <= 1800:
        return True, weak_hits[0]

    return False, ""


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


def enrich_story_with_article_metadata(story: dict, article_details: dict[str, str]) -> dict:
    enriched = dict(story)
    document_title = normalize_whitespace(str(article_details.get("document_title", "") or ""))
    document_excerpt = normalize_whitespace(str(article_details.get("document_excerpt", "") or ""))
    anchor_text = normalize_whitespace(str(enriched.get("anchor_text", "") or ""))

    if document_title and (not anchor_text or is_generic_title(anchor_text)):
        enriched["anchor_text"] = document_title
    if document_excerpt and (
        not str(enriched.get("context", "")).strip() or is_generic_title(anchor_text)
    ):
        enriched["context"] = trim_context(document_excerpt)
    return enriched
