from __future__ import annotations

import html
import re

from .config import DIGEST_TEMPLATE_PATH


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

    with DIGEST_TEMPLATE_PATH.open("r", encoding="utf-8") as handle:
        template_html = handle.read()
    return template_html.replace("{{CATEGORY_SECTIONS}}", "".join(category_sections))
