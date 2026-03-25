from __future__ import annotations

from datetime import UTC, datetime
import html
import re
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from .config import DIGEST_TEMPLATE_PATH, EMAIL_SAFE_DIGEST_TEMPLATE_PATH


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


PACIFIC_TIMEZONE = ZoneInfo("America/Los_Angeles")


def parse_story_datetime(published_at: str) -> datetime | None:
    raw = str(published_at or "").strip()
    if not raw:
        return None

    parsed = None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            parsed = None

    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def normalize_story_timestamp_iso(published_at: str) -> str:
    parsed = parse_story_datetime(published_at)
    if parsed is None:
        return ""
    return parsed.astimezone(UTC).isoformat()


def format_story_timestamp(published_at: str) -> str:
    parsed = parse_story_datetime(published_at)
    raw = str(published_at or "").strip()
    if parsed is None:
        return raw

    pacific = parsed.astimezone(PACIFIC_TIMEZONE)
    month = pacific.strftime("%b")
    day = pacific.day
    hour = pacific.strftime("%I").lstrip("0") or "12"
    minute = pacific.strftime("%M")
    meridiem = pacific.strftime("%p")
    return f"{month} {day}, {hour}:{minute} {meridiem} PT"


def build_render_groups(summaries: list[tuple[int, dict, str]]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for _, item, summary_block in summaries:
        title, url, body = parse_summary_block(summary_block)
        category = item.get("category", "") or "Uncategorized"
        grouped.setdefault(category, []).append(
            {
                "title": title,
                "url": url or item.get("url", ""),
                "body": body,
                "source_name": item.get("source_name", ""),
                "published_at": item.get("published_at", ""),
                "display_timestamp": format_story_timestamp(str(item.get("published_at", ""))),
                "timestamp_iso": normalize_story_timestamp_iso(str(item.get("published_at", ""))),
            }
        )
    return grouped


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


def split_summary_sections(body: str) -> tuple[list[str], list[str], list[str]]:
    takeaways: list[str] = []
    why_matters: list[str] = []
    other: list[str] = []
    active_section = "other"

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        normalized = re.sub(r"[:\s]+$", "", line).strip().lower()
        if normalized in {"key takeaways", "takeaways"}:
            active_section = "takeaways"
            continue
        if normalized in {"why this matters to me", "why this matters"}:
            active_section = "why_matters"
            continue

        bullet_match = re.match(r"^[-*]\s+(.+)$", line)
        content = bullet_match.group(1).strip() if bullet_match else line
        if not content:
            continue

        if active_section == "takeaways":
            takeaways.append(content)
        elif active_section == "why_matters":
            why_matters.append(content)
        else:
            other.append(content)

    return takeaways, why_matters, other


def render_digest_html(grouped: dict[str, list[dict]]) -> str:
    category_sections = []
    total_entries = 0
    for category, entries in grouped.items():
        total_entries += len(entries)
        cards = []
        count_label = "1 signal" if len(entries) == 1 else f"{len(entries)} signals"
        for index, entry in enumerate(entries, start=1):
            title = str(entry.get("title", "")).strip() or "Untitled"
            url = str(entry.get("url", "")).strip()
            body = str(entry.get("body", "")).strip()
            source_name = str(entry.get("source_name", "")).strip()
            timestamp = str(entry.get("display_timestamp", "")).strip()
            takeaways, why_matters, other = split_summary_sections(body)
            link_html = (
                f'<a href="{html.escape(url)}" target="_blank" rel="noreferrer noopener" class="story-link" style="color:#0c7a5b;text-decoration:none;font-weight:700;">Read original</a>'
                if url
                else ""
            )
            source_html = (
                f'<span class="story-source" style="display:inline-flex;align-items:center;min-height:28px;padding:0 12px;border-radius:999px;background:rgba(12,122,91,0.08);color:#5b6a78;font-size:12px;font-weight:700;letter-spacing:0.04em;">{html.escape(source_name)}</span>'
                if source_name
                else ""
            )
            time_html = (
                f'<span class="story-time" data-story-timestamp="{html.escape(str(entry.get("timestamp_iso", "")).strip())}" data-story-timestamp-fallback="{html.escape(timestamp)}" style="display:inline-flex;align-items:center;min-height:28px;padding:0 12px;border-radius:999px;background:rgba(12,122,91,0.08);color:#5b6a78;font-size:12px;font-weight:700;letter-spacing:0.04em;">{html.escape(timestamp)}</span>'
                if timestamp
                else ""
            )
            intro_html = "".join(
                (
                    '<p class="summary-paragraph" style="margin:0 0 10px 0;color:#2a3547;line-height:1.65;">'
                    f"{html.escape(paragraph)}"
                    "</p>"
                )
                for paragraph in other
            )
            takeaways_html = ""
            if takeaways:
                items_html = "".join(
                    (
                        '<li class="summary-list-item" style="margin:0 0 8px 0;">'
                        f"{html.escape(item)}"
                        "</li>"
                    )
                    for item in takeaways
                )
                takeaways_html = (
                    '<div class="summary-block" style="margin:0 0 14px 0;">'
                    '<div class="summary-heading" style="font-size:12px;font-weight:700;line-height:1.4;letter-spacing:0.14em;'
                    'text-transform:uppercase;color:#0f8661;margin:0 0 8px 0;">Key Signals</div>'
                    '<ul class="summary-list" style="margin:0 0 0 18px;padding:0;color:#243244;line-height:1.65;">'
                    f"{items_html}"
                    "</ul>"
                    "</div>"
                )
            why_html = ""
            if why_matters:
                why_text = " ".join(why_matters)
                why_html = (
                    '<div class="summary-note" style="margin:0 0 12px 0;padding:12px 14px;background:#eef8f4;'
                    'border:1px solid rgba(12,122,91,0.14);border-radius:16px;">'
                    '<div class="summary-heading" style="font-size:12px;font-weight:700;line-height:1.4;letter-spacing:0.14em;'
                    'text-transform:uppercase;color:#0c7a5b;margin:0 0 6px 0;">Why It Matters</div>'
                    f'<div class="summary-note-copy" style="margin:0;color:#2a3547;line-height:1.65;">{html.escape(why_text)}</div>'
                    '</div>'
                )
            if not intro_html and not takeaways_html and not why_html:
                intro_html = (
                    '<p class="summary-paragraph" style="margin:0 0 10px 0;color:#2a3547;line-height:1.65;">'
                    "No summary."
                    "</p>"
                )
            cards.append(
                (
                    '<div class="story-card" style="background:#ffffff;border:1px solid rgba(19,91,72,0.12);border-radius:24px;'
                    'padding:22px;margin:0 0 16px 0;box-shadow:0 10px 24px rgba(24,37,58,0.05);">'
                    '<div class="story-meta" style="display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin:0 0 14px 0;">'
                    f'<span class="story-chip" style="display:inline-flex;align-items:center;min-height:28px;padding:0 12px;border-radius:999px;background:#ddf3eb;color:#0c7a5b;font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;">Lead {index:02d}</span>'
                    f"{time_html}"
                    f"{source_html}"
                    "</div>"
                    f'<div class="story-title" style="font-family:Georgia,\'Times New Roman\',Times,serif;font-size:34px;font-weight:700;line-height:1.02;letter-spacing:-0.04em;color:#16222f;margin:0;max-width:24ch;overflow-wrap:anywhere;">{html.escape(title)}</div>'
                    '<div class="story-body" style="font-size:15px;line-height:1.65;color:#223240;margin:16px 0 12px 0;max-width:40rem;">'
                    f"{intro_html}"
                    f"{takeaways_html}"
                    f"{why_html}"
                    "</div>"
                    f'<div class="story-cta" style="font-size:14px;font-weight:600;">{link_html}</div>'
                    "</div>"
                )
            )
        category_sections.append(
            (
                '<div class="category-section" style="margin:0 0 24px 0;">'
                '<div class="category-head" style="display:flex;justify-content:space-between;gap:14px;align-items:flex-end;'
                'margin:0 0 12px 2px;padding:0 4px;">'
                f'<div class="category-title" style="font-family:Georgia,\'Times New Roman\',Times,serif;font-size:28px;font-weight:700;line-height:1.05;color:#16222f;letter-spacing:-0.03em;">{html.escape(category)}</div>'
                f'<div class="category-count" style="font-size:12px;font-weight:700;line-height:1.4;letter-spacing:0.14em;text-transform:uppercase;color:#0f8661;">{count_label}</div>'
                "</div>"
                f"{''.join(cards)}"
                "</div>"
            )
        )

    with DIGEST_TEMPLATE_PATH.open("r", encoding="utf-8") as handle:
        template_html = handle.read()
    rendered = template_html.replace("{{CATEGORY_SECTIONS}}", "".join(category_sections))
    return rendered.replace("{{HERO_COUNT}}", str(total_entries))


def render_email_safe_digest_html(grouped: dict[str, list[dict]]) -> str:
    category_sections = []
    total_entries = 0
    for category, entries in grouped.items():
        total_entries += len(entries)
        cards = []
        count_label = "1 signal" if len(entries) == 1 else f"{len(entries)} signals"
        for index, entry in enumerate(entries, start=1):
            title = str(entry.get("title", "")).strip() or "Untitled"
            url = str(entry.get("url", "")).strip()
            body = str(entry.get("body", "")).strip()
            source_name = str(entry.get("source_name", "")).strip()
            timestamp = str(entry.get("display_timestamp", "")).strip()
            takeaways, why_matters, other = split_summary_sections(body)
            link_html = (
                f'<a href="{html.escape(url)}" target="_blank" rel="noreferrer noopener" style="color:#0c7a5b;text-decoration:underline;font-weight:700;">Read original</a>'
                if url
                else ""
            )

            metadata_parts = []
            if timestamp:
                metadata_parts.append(html.escape(timestamp))
            if source_name:
                metadata_parts.append(html.escape(source_name))
            metadata_line = " | ".join(metadata_parts)
            metadata_html = (
                f'<div style="margin:0 0 10px 0;font-size:12px;line-height:1.5;color:#5b6a78;">{metadata_line}</div>'
                if metadata_line
                else ""
            )

            takeaways_html = ""
            if takeaways:
                items_html = "".join(
                    f'<li style="margin:0 0 8px 0;">{html.escape(item)}</li>' for item in takeaways
                )
                takeaways_html = (
                    '<div style="margin:0 0 12px 0;">'
                    '<div style="margin:0 0 6px 0;font-size:12px;line-height:1.4;color:#0c7a5b;'
                    'font-weight:700;text-transform:uppercase;letter-spacing:0.06em;">Key takeaways</div>'
                    f'<ul style="margin:0 0 0 18px;padding:0;font-size:15px;line-height:1.6;color:#223240;">{items_html}</ul>'
                    '</div>'
                )

            why_html = ""
            if why_matters:
                why_text = " ".join(why_matters)
                why_html = (
                    '<div style="margin:0 0 12px 0;padding:10px 12px;background:#eef8f4;'
                    'border:1px solid #d7efe6;border-radius:12px;">'
                    '<div style="margin:0 0 4px 0;font-size:12px;line-height:1.4;color:#5b6a78;'
                    'font-weight:700;text-transform:uppercase;letter-spacing:0.06em;">Why this matters</div>'
                    f'<div style="font-size:14px;line-height:1.6;color:#223240;">{html.escape(why_text)}</div>'
                    '</div>'
                )

            other_html = ""
            if other:
                other_html = "".join(
                    (
                        '<p style="margin:0 0 10px 0;font-size:14px;line-height:1.6;color:#223240;">'
                        f"{html.escape(paragraph)}"
                        "</p>"
                    )
                    for paragraph in other
                )
            if not takeaways_html and not why_html and not other_html:
                other_html = '<p style="margin:0 0 10px 0;font-size:14px;line-height:1.6;color:#223240;">No summary.</p>'

            cards.append(
                (
                    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                    'style="border-collapse:separate;background:#ffffff;border:1px solid #d5dde8;border-radius:18px;margin:0 0 14px 0;">'
                    '<tr><td style="padding:14px 14px 12px 14px;">'
                    f'<div style="margin:0 0 10px 0;font-size:11px;line-height:1.4;color:#0f8661;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;">Lead {index:02d}</div>'
                    f"{metadata_html}"
                    f'<div style="margin:0 0 12px 0;font-size:24px;line-height:1.08;font-weight:700;color:#16222f;font-family:Georgia,\'Times New Roman\',Times,serif;">{html.escape(title)}</div>'
                    f"{other_html}"
                    f"{takeaways_html}"
                    f"{why_html}"
                    f'<div style="margin-top:12px;font-size:14px;line-height:1.5;">{link_html}</div>'
                    "</td></tr></table>"
                )
            )
        category_sections.append(
            (
                '<div style="margin:0 0 18px 0;">'
                f'<div style="margin:0 0 10px 0;padding:0 4px;font-size:13px;line-height:1.4;color:#0f8661;'
                'font-weight:700;text-transform:uppercase;letter-spacing:0.08em;">'
                f'{html.escape(category)} <span style="color:#6f7f87;font-weight:600;">({count_label})</span>'
                '</div>'
                f"{''.join(cards)}"
                '</div>'
            )
        )

    with EMAIL_SAFE_DIGEST_TEMPLATE_PATH.open("r", encoding="utf-8") as handle:
        template_html = handle.read()
    rendered = template_html.replace("{{CATEGORY_SECTIONS}}", "".join(category_sections))
    return rendered.replace("{{HERO_COUNT}}", str(total_entries))
