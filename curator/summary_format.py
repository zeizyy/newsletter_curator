from __future__ import annotations

import json
import re


def split_summary_sections(body: str) -> tuple[list[str], list[str], list[str]]:
    takeaways: list[str] = []
    why_matters: list[str] = []
    other: list[str] = []
    active_section = "other"

    for raw_line in str(body or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        bullet_match = re.match(r"^[-*]\s+(.+)$", line)
        candidate = bullet_match.group(1).strip() if bullet_match else line
        if not candidate:
            continue

        inline_takeaways_match = re.match(r"^(?:key takeaways|takeaways)\s*:\s*(.+)$", candidate, re.IGNORECASE)
        if inline_takeaways_match:
            active_section = "takeaways"
            takeaways.append(inline_takeaways_match.group(1).strip())
            continue

        inline_why_match = re.match(
            r"^(?:why this matters to me|why this matters)\s*:\s*(.+)$",
            candidate,
            re.IGNORECASE,
        )
        if inline_why_match:
            active_section = "why_matters"
            why_matters.append(inline_why_match.group(1).strip())
            continue

        normalized = re.sub(r"[:\s]+$", "", candidate).strip().lower()
        if normalized in {"key takeaways", "takeaways"}:
            active_section = "takeaways"
            continue
        if normalized in {"why this matters to me", "why this matters"}:
            active_section = "why_matters"
            continue

        if active_section == "takeaways":
            takeaways.append(candidate)
        elif active_section == "why_matters":
            why_matters.append(candidate)
        else:
            other.append(candidate)

    return takeaways, why_matters, other


def format_summary_body(
    *,
    key_takeaways: list[str],
    why_this_matters: str,
    other_paragraphs: list[str] | None = None,
) -> str:
    sections: list[str] = []
    cleaned_other = [str(paragraph).strip() for paragraph in (other_paragraphs or []) if str(paragraph).strip()]
    cleaned_takeaways = [str(item).strip() for item in key_takeaways if str(item).strip()]
    cleaned_why = str(why_this_matters or "").strip()

    if cleaned_other:
        sections.append("\n".join(cleaned_other))
    if cleaned_takeaways:
        sections.append("\n".join(["Key takeaways", *[f"- {item}" for item in cleaned_takeaways]]))
    if cleaned_why:
        sections.append("\n".join(["Why this matters to me", cleaned_why]))
    return "\n\n".join(section for section in sections if section.strip()).strip()


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _repair_invalid_json_escapes(text: str) -> str:
    return re.sub(r"\\(?![\"\\/bfnrtu])", "", text)


def _parse_summary_payload(summary: str) -> dict | None:
    candidates = [summary, _extract_json_object(summary)]
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return payload

    repaired_candidates = [_repair_invalid_json_escapes(candidate) for candidate in candidates]
    for candidate in repaired_candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return payload

    for candidate in repaired_candidates:
        headline_match = re.search(r'"headline"\s*:\s*"(?P<value>(?:[^"\\]|\\.)*)"', candidate)
        body_match = re.search(
            r'"body"\s*:\s*"(?P<value>(?:[^"\\]|\\.)*)"',
            candidate,
            flags=re.DOTALL,
        )
        if not headline_match and not body_match:
            continue
        headline = (
            bytes((headline_match.group("value") if headline_match else "").strip(), "utf-8").decode(
                "unicode_escape"
            )
            if headline_match
            else ""
        )
        body = (
            bytes((body_match.group("value") if body_match else "").strip(), "utf-8").decode(
                "unicode_escape"
            )
            if body_match
            else ""
        )
        return {"headline": headline, "body": body}
    return None


def normalize_summary_payload(
    payload: dict | None,
    *,
    fallback_headline: str = "",
    fallback_body: str = "",
) -> dict[str, str | list[str]]:
    payload = payload if isinstance(payload, dict) else {}
    headline = str(payload.get("headline", "") or fallback_headline or "Untitled").strip() or "Untitled"
    raw_body = str(payload.get("body", "") or fallback_body).strip()

    raw_takeaways = payload.get("key_takeaways")
    if not isinstance(raw_takeaways, list):
        raw_takeaways = []
    key_takeaways = [str(item).strip() for item in raw_takeaways if str(item).strip()]

    why_this_matters = str(
        payload.get("why_this_matters", "") or payload.get("why_matters", "") or ""
    ).strip()

    parsed_takeaways, parsed_why_lines, parsed_other = split_summary_sections(raw_body)
    if not key_takeaways:
        key_takeaways = parsed_takeaways
    if not why_this_matters and parsed_why_lines:
        why_this_matters = " ".join(parsed_why_lines).strip()

    body = (
        format_summary_body(
            key_takeaways=key_takeaways,
            why_this_matters=why_this_matters,
            other_paragraphs=parsed_other,
        )
        or raw_body
    )

    return {
        "headline": headline,
        "key_takeaways": key_takeaways,
        "why_this_matters": why_this_matters,
        "other_paragraphs": parsed_other,
        "body": body,
    }


def extract_structured_summary(
    summary: str,
    *,
    fallback_headline: str = "",
    fallback_body: str = "",
) -> dict[str, str | list[str]]:
    payload = _parse_summary_payload(str(summary or ""))
    return normalize_summary_payload(
        payload,
        fallback_headline=fallback_headline,
        fallback_body=fallback_body,
    )


def canonicalize_summary_json(
    summary: str,
    *,
    fallback_headline: str = "",
    fallback_body: str = "",
) -> tuple[str, dict[str, str | list[str]]]:
    normalized = extract_structured_summary(
        summary,
        fallback_headline=fallback_headline,
        fallback_body=fallback_body,
    )
    canonical = json.dumps(
        {
            "headline": normalized["headline"],
            "key_takeaways": normalized["key_takeaways"],
            "why_this_matters": normalized["why_this_matters"],
        },
        sort_keys=True,
    )
    return canonical, normalized
