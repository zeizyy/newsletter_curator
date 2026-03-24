from __future__ import annotations

import json
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests
from trafilatura import extract

MAX_FETCH_RESPONSE_BYTES = 2_000_000
FETCH_CHUNK_SIZE_BYTES = 64 * 1024


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

BLOCKED_PLACEHOLDER_STRONG_MARKERS = {
    "site content blocked due to javascript being disabled": "javascript_disabled_placeholder",
    "page failed to load javascript is disabled": "javascript_disabled_placeholder",
    "page failed to load - javascript is disabled": "javascript_disabled_placeholder",
    "page failed to load — javascript is disabled": "javascript_disabled_placeholder",
    "please enable javascript to continue": "javascript_required_placeholder",
    "javascript is disabled or blocked": "javascript_required_placeholder",
    "ad blocker detected": "adblock_detected_placeholder",
    "disable your ad blocker": "adblock_required_placeholder",
    "turn off your ad blocker": "adblock_required_placeholder",
}

PAYWALL_DOM_TOKENS = {
    "paywall",
    "gateway",
    "subscriber-only",
    "subscriber_only",
    "subscription",
    "subscribe",
    "premium",
    "metered",
    "meter",
    "regwall",
    "registration-wall",
}

BLOCKED_DOM_TOKENS = {
    "js-required",
    "javascript-required",
    "enable-javascript",
    "enable_javascript",
    "adblock",
    "ad-block",
    "paywall-modal",
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

    access = classify_article_access(
        article_text=article_text[:max_article_chars],
        url=url,
        document_title=title,
        document_excerpt=excerpt,
        raw_html=html,
    )

    return {
        "article_text": article_text[:max_article_chars],
        "document_title": title,
        "document_excerpt": excerpt,
        "access_blocked": access["blocked"],
        "access_reason": access["reason"],
        "access_signals": access["signals"],
    }


def _read_response_text_limited(
    response: requests.Response,
    *,
    max_response_bytes: int | None = None,
) -> tuple[str, bool]:
    max_response_bytes = max_response_bytes or MAX_FETCH_RESPONSE_BYTES
    chunks: list[bytes] = []
    total_bytes = 0
    truncated = False

    for chunk in response.iter_content(chunk_size=FETCH_CHUNK_SIZE_BYTES):
        if not chunk:
            continue
        remaining = max_response_bytes - total_bytes
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            total_bytes += remaining
            truncated = True
            break
        chunks.append(chunk)
        total_bytes += len(chunk)

    encoding = response.encoding or "utf-8"
    return b"".join(chunks).decode(encoding, errors="replace"), truncated


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
                response = session.get(url, headers=headers, timeout=timeout, stream=True)
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < retries:
                    continue
                raise last_exc
        if response is None:
            return {"article_text": "", "document_title": "", "document_excerpt": ""}
        try:
            response_text, truncated = _read_response_text_limited(response)
            if truncated:
                print(f"Truncated article response: {url} ({MAX_FETCH_RESPONSE_BYTES} bytes cap)")
            return extract_article_details_from_html(
                response_text,
                url=url,
                max_article_chars=max_article_chars,
            )
        finally:
            response.close()
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


def detect_paywalled_article(
    article_text: str,
    url: str = "",
    *,
    document_title: str = "",
    document_excerpt: str = "",
    raw_html: str = "",
) -> tuple[bool, str]:
    access = classify_article_access(
        article_text,
        url,
        document_title=document_title,
        document_excerpt=document_excerpt,
        raw_html=raw_html,
    )
    return bool(access["blocked"]), str(access["reason"])


def _parse_json_ld_objects(raw_html: str) -> list[dict]:
    soup = BeautifulSoup(raw_html, "html.parser")
    objects: list[dict] = []
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = node.string or node.get_text(" ", strip=True) or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                objects.append(current)
                graph = current.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
                elif isinstance(graph, dict):
                    stack.append(graph)
                for value in current.values():
                    if isinstance(value, list):
                        stack.extend(v for v in value if isinstance(v, (dict, list)))
                    elif isinstance(value, dict):
                        stack.append(value)
            elif isinstance(current, list):
                stack.extend(item for item in current if isinstance(item, (dict, list)))
    return objects


def _node_token_blob(node) -> str:
    if node is None:
        return ""
    tokens: list[str] = []
    for attr_name in ("class", "id", "data-testid", "data-name", "aria-label"):
        value = node.get(attr_name)
        if isinstance(value, list):
            tokens.extend(str(part) for part in value if str(part).strip())
        elif value:
            tokens.append(str(value))
    return " ".join(tokens).lower()


def classify_article_access(
    article_text: str,
    url: str = "",
    *,
    document_title: str = "",
    document_excerpt: str = "",
    raw_html: str = "",
) -> dict:
    article_text_normalized = normalize_whitespace(article_text)
    text = article_text_normalized.lower()
    combined_text = normalize_whitespace(
        " ".join(
            part
            for part in [document_title, document_excerpt, article_text_normalized]
            if str(part or "").strip()
        )
    ).lower()
    signals: dict[str, object] = {
        "word_count": len(article_text_normalized.split()),
        "has_structured_paywall": False,
        "structured_selector_hit": False,
        "dom_paywall_token_hit": False,
        "dom_blocked_token_hit": False,
        "strong_text_markers": [],
        "weak_text_markers": [],
        "blocked_text_markers": [],
    }

    soup = BeautifulSoup(raw_html, "html.parser") if raw_html else None
    if raw_html:
        for obj in _parse_json_ld_objects(raw_html):
            free_value = obj.get("isAccessibleForFree")
            if isinstance(free_value, str):
                free_value = free_value.lower() == "true"
            if free_value is False:
                signals["has_structured_paywall"] = True
                has_part = obj.get("hasPart")
                parts = has_part if isinstance(has_part, list) else [has_part]
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    part_free = part.get("isAccessibleForFree")
                    if isinstance(part_free, str):
                        part_free = part_free.lower() == "true"
                    selector = str(part.get("cssSelector", "") or "").strip()
                    if part_free is False and selector and soup is not None:
                        try:
                            if soup.select(selector):
                                signals["structured_selector_hit"] = True
                        except Exception:
                            pass
                return {"blocked": True, "reason": "structured_data_paywall", "signals": signals}

    if soup is not None:
        token_hits = 0
        blocked_hits = 0
        for node in soup.find_all(True):
            blob = _node_token_blob(node)
            if not blob:
                continue
            if any(token in blob for token in PAYWALL_DOM_TOKENS):
                token_hits += 1
            if any(token in blob for token in BLOCKED_DOM_TOKENS):
                blocked_hits += 1
        signals["dom_paywall_token_hit"] = token_hits > 0
        signals["dom_blocked_token_hit"] = blocked_hits > 0

    strong_hits = [reason for marker, reason in PAYWALL_STRONG_MARKERS.items() if marker in text]
    blocked_hits = [
        reason for marker, reason in BLOCKED_PLACEHOLDER_STRONG_MARKERS.items() if marker in combined_text
    ]
    weak_hits = [reason for marker, reason in PAYWALL_WEAK_MARKERS.items() if marker in text]
    signals["strong_text_markers"] = strong_hits
    signals["weak_text_markers"] = weak_hits
    signals["blocked_text_markers"] = blocked_hits

    if strong_hits and len(text) <= 2500:
        return {"blocked": True, "reason": strong_hits[0], "signals": signals}

    if blocked_hits and len(article_text_normalized) <= 3000:
        return {"blocked": True, "reason": blocked_hits[0], "signals": signals}

    if (
        ("javascript" in combined_text and ("disabled" in combined_text or "blocked" in combined_text))
        and ("enable" in combined_text or "required" in combined_text)
        and len(article_text_normalized) <= 3000
    ):
        return {"blocked": True, "reason": "javascript_required_placeholder", "signals": signals}

    if (
        "ad blocker" in combined_text
        and ("disable" in combined_text or "turn off" in combined_text or "detected" in combined_text)
        and len(article_text_normalized) <= 3000
    ):
        return {"blocked": True, "reason": "adblock_required_placeholder", "signals": signals}

    parsed = urlparse(url)
    paywallish_path = any(
        token in parsed.path.lower()
        for token in ["/subscribe", "/subscription", "/member", "/login", "/signin", "/premium"]
    )

    if len(weak_hits) >= 2 and len(text) <= 1500:
        return {"blocked": True, "reason": weak_hits[0], "signals": signals}
    if weak_hits and paywallish_path and len(text) <= 1800:
        return {"blocked": True, "reason": weak_hits[0], "signals": signals}
    if signals["dom_paywall_token_hit"] and weak_hits and len(text) <= 2200:
        return {"blocked": True, "reason": "dom_paywall_overlay", "signals": signals}
    if signals["dom_blocked_token_hit"] and len(article_text_normalized) <= 3000:
        return {"blocked": True, "reason": "dom_blocked_placeholder", "signals": signals}

    return {"blocked": False, "reason": "", "signals": signals}


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
