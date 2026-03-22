from __future__ import annotations

import html
import re
from datetime import UTC, datetime

from .config import DIGEST_TEMPLATE_PATH


def group_summaries_by_category(summaries: list[tuple[int, dict, str]]) -> dict:
    grouped = {}
    for ordinal, item, summary in summaries:
        category = item.get("category", "") or "Uncategorized"
        title, url, body = parse_summary_block(summary)
        grouped.setdefault(category, []).append(
            {
                "ordinal": ordinal,
                "summary_block": summary,
                "title": title,
                "url": url,
                "body": body,
                "source_name": str(item.get("source_name", "")).strip(),
                "source_type": str(item.get("source_type", "")).strip(),
                "published_at": str(item.get("published_at", "")).strip(),
                "score": item.get("score", ""),
            }
        )
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
            heading_class = "summary-heading"
            heading_style = (
                "font-size:15px;font-weight:700;line-height:1.35;color:#152238;margin:14px 0 7px 0;"
            )
            if "why this matters" in heading_text.lower():
                heading_class += " summary-heading-emphasis"
                heading_style = (
                    "font-size:12px;font-weight:800;line-height:1.35;color:#0c5f5b;margin:14px 0 7px 0;"
                    "letter-spacing:0.08em;text-transform:uppercase;"
                )
            blocks.append(
                (
                    f'<div class="{heading_class}" style="{heading_style}">'
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


def format_story_date(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).strftime("%b %d")
    except ValueError:
        return cleaned[:10]


def render_digest_html(grouped: dict[str, list[str]]) -> str:
    total_story_count = sum(len(entries) for entries in grouped.values())
    category_sections = []
    for category, entries in grouped.items():
        cards = []
        for entry in entries:
            body_html = render_summary_body_html(entry["body"])
            source_name = entry.get("source_name", "")
            published_label = format_story_date(entry.get("published_at", ""))
            meta_segments = []
            if source_name:
                meta_segments.append(
                    '<span class="story-source-pill" style="display:inline-flex;align-items:center;gap:6px;'
                    'background:#eef4fb;border:1px solid #d4e0ee;border-radius:999px;padding:4px 10px;'
                    'font-size:12px;font-weight:700;color:#2c4f73;">'
                    f"{html.escape(source_name)}"
                    "</span>"
                )
            if published_label:
                meta_segments.append(
                    '<span class="story-date-pill" style="display:inline-flex;align-items:center;gap:6px;'
                    'background:#f7efe0;border:1px solid #ead7b2;border-radius:999px;padding:4px 10px;'
                    'font-size:12px;font-weight:700;color:#7a5a19;">'
                    f"{html.escape(published_label)}"
                    "</span>"
                )
            link_html = (
                f'<a href="{html.escape(entry["url"])}" class="story-link" style="display:inline-flex;align-items:center;gap:8px;'
                'color:#0b57d0;text-decoration:none;">Read article<span aria-hidden="true">→</span></a>'
                if entry["url"]
                else ""
            )
            cards.append(
                (
                    '<div class="story-card" style="background:#ffffff;border:1px solid #dce7f2;border-radius:18px;'
                    'padding:20px 20px 18px 20px;margin:0 0 14px 0;box-shadow:0 10px 30px rgba(26,50,87,0.08);">'
                    '<div class="story-card-header" style="display:flex;justify-content:space-between;align-items:flex-start;gap:14px;'
                    'margin:0 0 12px 0;flex-wrap:wrap;">'
                    '<div class="story-meta-row" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">'
                    f'<div class="story-index" style="width:28px;height:28px;border-radius:999px;background:#12345b;color:#ffffff;'
                    'display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:800;">'
                    f"{entry['ordinal']}</div>"
                    f"{''.join(meta_segments)}"
                    '</div>'
                    '</div>'
                    f'<div class="story-title" style="font-size:24px;font-weight:760;line-height:1.22;color:#152238;margin:0 0 10px 0;">{html.escape(entry["title"])}</div>'
                    f'<div class="story-body" style="font-size:15px;line-height:1.72;color:#25364d;margin:0 0 14px 0;">{body_html}</div>'
                    f'<div class="story-cta" style="font-size:14px;font-weight:700;">{link_html}</div>'
                    "</div>"
                )
            )
        category_sections.append(
            (
                '<div class="category-section" style="margin:0 0 26px 0;">'
                '<div class="category-kicker" style="font-size:11px;font-weight:800;letter-spacing:0.12em;'
                'text-transform:uppercase;color:#6c84a5;margin:0 0 6px 0;">Section</div>'
                f'<div class="category-title" style="font-size:26px;font-weight:760;line-height:1.18;color:#243b5a;'
                f'margin:0 0 12px 0;">{html.escape(category)}</div>'
                f"{''.join(cards)}"
                "</div>"
            )
        )

    with DIGEST_TEMPLATE_PATH.open("r", encoding="utf-8") as handle:
        template_html = handle.read()
    return (
        template_html.replace("{{CATEGORY_SECTIONS}}", "".join(category_sections))
        .replace("{{STORY_COUNT}}", str(total_story_count))
    )
