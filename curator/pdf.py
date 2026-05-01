from __future__ import annotations

from io import BytesIO
from typing import Iterable
from xml.sax.saxutils import escape

from .rendering import flatten_render_payload, format_story_timestamp
from .summary_format import extract_structured_summary


_PDF_TEXT_TRANSLATION = str.maketrans(
    {
        "\u00a0": " ",
        "\u2007": " ",
        "\u202f": " ",
        "\u200b": "",
        "\ufeff": "",
        "\u2010": "-",
        "\u2011": "-",
        "\u2212": "-",
    }
)


def _pdf_safe_text(text: str) -> str:
    return str(text or "").translate(_PDF_TEXT_TRANSLATION)


def _pdf_paragraph(text: str, style):
    from reportlab.platypus import Paragraph

    return Paragraph(escape(_pdf_safe_text(text)), style)


def _text_blocks(text: str) -> list[str]:
    normalized = _pdf_safe_text(text).replace("\r\n", "\n").strip()
    if not normalized:
        return []
    return [block.strip() for block in normalized.split("\n\n") if block.strip()]


def _story_payloads(render_payload) -> Iterable[dict]:
    for entry in flatten_render_payload(render_payload):
        fallback_title = str(entry.get("title", "")).strip() or "Untitled"
        fallback_body = str(entry.get("body", "")).strip()
        normalized = extract_structured_summary(
            str(entry.get("summary_raw", "") or ""),
            fallback_headline=fallback_title,
            fallback_body=fallback_body,
        )
        key_takeaways = [
            _pdf_safe_text(item).strip()
            for item in normalized.get("key_takeaways", [])
            if _pdf_safe_text(item).strip()
        ]
        why_this_matters = _pdf_safe_text(str(normalized.get("why_this_matters", "") or "")).strip()
        body_blocks = [
            _pdf_safe_text(block).strip()
            for block in normalized.get("other_paragraphs", [])
            if _pdf_safe_text(block).strip()
        ]
        if not body_blocks and not key_takeaways and not why_this_matters:
            body_blocks = _text_blocks(str(normalized.get("body", "") or fallback_body))

        yield {
            "title": str(normalized.get("headline", "") or fallback_title).strip() or "Untitled",
            "source_name": _pdf_safe_text(str(entry.get("source_name", "") or "")).strip(),
            "display_timestamp": _pdf_safe_text(
                str(entry.get("display_timestamp", "") or "").strip()
                or format_story_timestamp(str(entry.get("published_at", "") or ""))
            ),
            "body_blocks": body_blocks,
            "key_takeaways": key_takeaways,
            "why_this_matters": why_this_matters,
            "url": _pdf_safe_text(str(entry.get("url", "") or "")).strip(),
        }


def render_digest_pdf(
    render_payload,
    *,
    subject: str,
    newsletter_date: str,
    fallback_text: str = "",
) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import inch
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:
        raise RuntimeError("PDF delivery requires the reportlab package.") from exc

    page_size = (5.6 * inch, 8.4 * inch)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=0.45 * inch,
        rightMargin=0.45 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=str(subject or "").strip() or "AI Signal Daily",
        author="Newsletter Curator",
    )

    base_styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DigestTitle",
        parent=base_styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#111827"),
        spaceAfter=8,
    )
    meta_style = ParagraphStyle(
        "DigestMeta",
        parent=base_styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=10.5,
        textColor=colors.HexColor("#4b5563"),
        spaceAfter=6,
    )
    heading_style = ParagraphStyle(
        "StoryHeading",
        parent=base_styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13.5,
        leading=16.5,
        textColor=colors.HexColor("#111827"),
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "StoryBody",
        parent=base_styles["BodyText"],
        fontName="Times-Roman",
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#1f2937"),
        spaceAfter=6,
    )
    label_style = ParagraphStyle(
        "StoryLabel",
        parent=base_styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#0f766e"),
        spaceAfter=4,
    )
    link_style = ParagraphStyle(
        "StoryLink",
        parent=base_styles["BodyText"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#475569"),
        spaceAfter=8,
    )

    elements = [
        _pdf_paragraph(str(subject or "").strip() or "AI Signal Daily", title_style),
    ]
    if str(newsletter_date or "").strip():
        elements.append(_pdf_paragraph(str(newsletter_date).strip(), meta_style))
    elements.append(Spacer(1, 10))

    story_payloads = list(_story_payloads(render_payload))
    if story_payloads:
        for index, story in enumerate(story_payloads, start=1):
            metadata = " | ".join(
                value
                for value in [
                    f"Story {index}",
                    story["source_name"],
                    story["display_timestamp"],
                ]
                if value
            )
            if metadata:
                elements.append(_pdf_paragraph(metadata, meta_style))
            elements.append(_pdf_paragraph(story["title"], heading_style))
            body_blocks = story["body_blocks"]
            if not body_blocks and not story["key_takeaways"] and not story["why_this_matters"]:
                body_blocks = ["No summary."]
            for paragraph in body_blocks:
                elements.append(_pdf_paragraph(paragraph, body_style))
            if story["key_takeaways"]:
                elements.append(Paragraph("KEY TAKEAWAYS", label_style))
                for takeaway in story["key_takeaways"]:
                    elements.append(_pdf_paragraph(f"- {takeaway}", body_style))
            if story["why_this_matters"]:
                elements.append(Paragraph("WHY THIS MATTERS", label_style))
                elements.append(_pdf_paragraph(story["why_this_matters"], body_style))
            if story["url"]:
                elements.append(_pdf_paragraph(f"Read original: {story['url']}", link_style))
            elements.append(HRFlowable(color=colors.HexColor("#d1d5db"), width="100%", thickness=0.5))
            elements.append(Spacer(1, 10))
    else:
        for paragraph in _text_blocks(fallback_text) or ["No newsletter content was available."]:
            elements.append(_pdf_paragraph(paragraph, body_style))

    def _decorate_page(canvas, doc):  # pragma: no cover - exercised via PDF bytes generation
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 18, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(elements, onFirstPage=_decorate_page, onLaterPages=_decorate_page)
    return buffer.getvalue()
