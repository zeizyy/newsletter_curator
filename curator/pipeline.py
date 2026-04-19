from __future__ import annotations

from collections import Counter
import inspect
from threading import Lock

from .content import dedupe_links_by_url, extract_links_from_html, fetch_article_text
from .gmail import (
    collect_live_gmail_links,
    extract_bodies,
    get_header_value,
    get_label_id,
    get_message,
    list_message_ids_for_label,
    send_email,
)
from .llm import extract_summary_json, select_top_stories, summarize_article_with_llm
from .rendering import (
    build_render_groups,
    group_summaries_by_category,
    parse_story_datetime,
    parse_summary_block,
    render_email_safe_digest_html,
    render_digest_html,
    render_digest_text,
)
from .sources import collect_additional_source_links
from .observability import compact_model_usage, emit_event


def _render_html_with_issue_type(render_html_fn, render_groups, *, issue_type: str) -> str:
    signature = inspect.signature(render_html_fn)
    parameters = signature.parameters
    accepts_issue_type = "issue_type" in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    if accepts_issue_type:
        return render_html_fn(render_groups, issue_type=issue_type)
    return render_html_fn(render_groups)


def process_story(
    item: dict,
    usage_by_model: dict,
    lock: Lock,
    max_article_chars: int,
    summary_model: str,
    *,
    article_fetcher=fetch_article_text,
    summarize_article_with_llm_fn=summarize_article_with_llm,
) -> str | None:
    stored_headline = str(item.get("summary_headline", "")).strip()
    stored_body = str(item.get("summary_body", "")).strip()
    if stored_body:
        headline = stored_headline or str(item.get("anchor_text", "")).strip() or "Untitled"
        return "\n\n".join(
            [
                f"Story: {headline}",
                f"URL: {item.get('url', '')}",
                stored_body,
            ]
        )

    article_text = str(item.get("article_text", "") or "").strip()
    if not article_text:
        article_text = article_fetcher(item.get("url", ""), max_article_chars)
    if not article_text:
        return None
    summary = summarize_article_with_llm_fn(article_text, usage_by_model, lock, summary_model)
    headline, body = extract_summary_json(summary)
    if not body.strip() or body.strip() == "No article text available.":
        return None
    item["summary_raw"] = str(summary or "")
    item["summary_headline"] = headline
    item["summary_body"] = body
    return "\n\n".join(
        [
            f"Story: {headline}",
            f"URL: {item.get('url', '')}",
            body,
        ]
    )


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


def story_day_key(item: dict) -> str:
    parsed = parse_story_datetime(str(item.get("published_at", "") or item.get("date", "")))
    if parsed is not None:
        return parsed.date().isoformat()
    raw = str(item.get("published_at", "") or item.get("date", "")).strip()
    if len(raw) >= 10:
        return raw[:10]
    return "unknown"


def cap_links_per_day(items: list[dict], max_per_day: int) -> list[dict]:
    if max_per_day <= 0:
        return list(items)
    counts: dict[str, int] = {}
    capped: list[dict] = []
    for item in items:
        day_key = story_day_key(item)
        if counts.get(day_key, 0) >= max_per_day:
            continue
        capped.append(item)
        counts[day_key] = counts.get(day_key, 0) + 1
    return capped


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


def _ordered_counts(
    items: list[dict], field: str, top_n: int | None = None, missing_label: str = "unknown"
) -> list[tuple[str, int]]:
    counts = Counter((str(item.get(field, "")).strip() or missing_label) for item in items)
    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    if top_n is not None:
        ordered = ordered[:top_n]
    return ordered


def format_counts(
    items: list[dict], field: str, top_n: int | None = None, missing_label: str = "unknown"
) -> str:
    ordered = _ordered_counts(items, field, top_n=top_n, missing_label=missing_label)
    return ", ".join(f"{name}={count}" for name, count in ordered) if ordered else "none"


def structured_counts(
    items: list[dict], field: str, top_n: int | None = None, missing_label: str = "unknown"
) -> list[dict[str, int | str]]:
    return [
        {"name": name, "count": count}
        for name, count in _ordered_counts(items, field, top_n=top_n, missing_label=missing_label)
    ]


def normalize_allowed_source_names(
    preferred_sources: list[str] | tuple[str, ...] | None,
) -> set[str]:
    return {
        str(source).strip().lower()
        for source in preferred_sources or []
        if str(source).strip()
    }


def filter_links_to_allowed_sources(
    items: list[dict],
    allowed_source_names: set[str],
) -> list[dict]:
    if not allowed_source_names:
        return list(items)
    return [
        item
        for item in items
        if str(item.get("source_name", "")).strip().lower() in allowed_source_names
    ]


def run_job(
    config: dict,
    service,
    *,
    collect_gmail_links_fn=None,
    get_label_id_fn=get_label_id,
    list_message_ids_for_label_fn=list_message_ids_for_label,
    get_message_fn=get_message,
    extract_bodies_fn=extract_bodies,
    get_header_value_fn=get_header_value,
    extract_links_from_html_fn=extract_links_from_html,
    collect_additional_source_links_fn=collect_additional_source_links,
    dedupe_links_by_url_fn=dedupe_links_by_url,
    select_top_stories_fn=select_top_stories,
    process_story_fn=process_story,
    group_summaries_by_category_fn=group_summaries_by_category,
    build_render_groups_fn=build_render_groups,
    render_digest_text_fn=render_digest_text,
    render_digest_html_fn=render_digest_html,
    render_email_safe_digest_html_fn=render_email_safe_digest_html,
    send_email_fn=send_email,
    preferred_sources: list[str] | tuple[str, ...] | None = None,
) -> None:
    gmail_cfg = config["gmail"]
    openai_cfg = config["openai"]
    limits_cfg = config["limits"]
    email_cfg = config["email"]

    query = gmail_cfg["query_time_window"]
    live_gmail_collector = collect_gmail_links_fn or (
        lambda cfg, svc: collect_live_gmail_links(
            svc,
            cfg,
            get_label_id_fn=get_label_id_fn,
            list_message_ids_for_label_fn=list_message_ids_for_label_fn,
            get_message_fn=get_message_fn,
            extract_bodies_fn=extract_bodies_fn,
            get_header_value_fn=get_header_value_fn,
            extract_links_from_html_fn=extract_links_from_html_fn,
        )
    )
    gmail_links = live_gmail_collector(config, service)
    all_links = list(gmail_links)
    gmail_links_count = len(gmail_links)
    source_links = collect_additional_source_links_fn(config)
    all_links.extend(source_links)
    all_links = dedupe_links_by_url_fn(all_links)
    allowed_source_names = normalize_allowed_source_names(preferred_sources)
    eligible_links = filter_links_to_allowed_sources(all_links, allowed_source_names)
    uncapped_eligible_links = len(eligible_links)
    weekly_cfg = (
        config.get("weekly", {}) if config.get("delivery", {}).get("issue_type") == "weekly" else {}
    )
    max_stories_per_day = int(weekly_cfg.get("max_stories_per_day", 0) or 0)
    if max_stories_per_day > 0:
        eligible_links = cap_links_per_day(eligible_links, max_stories_per_day)
        emit_event(
            "pipeline_weekly_candidate_cap_applied",
            max_stories_per_day=max_stories_per_day,
            uncapped_eligible_links=uncapped_eligible_links,
            capped_eligible_links=len(eligible_links),
        )
    emit_event(
        "pipeline_candidates_collected",
        gmail_query=query,
        gmail_links=gmail_links_count,
        additional_source_links=len(source_links),
        deduped_links=len(all_links),
        eligible_links=len(eligible_links),
        uncapped_eligible_links=uncapped_eligible_links,
        weekly_max_stories_per_day=max_stories_per_day,
        preferred_sources=sorted(allowed_source_names),
        source_type_counts=structured_counts(all_links, "source_type"),
        source_name_counts_top10=structured_counts(all_links, "source_name", top_n=10),
    )

    result = {
        "status": "running",
        "gmail_links": len(gmail_links),
        "additional_source_links": len(source_links),
        "deduped_links": len(all_links),
        "eligible_links": len(eligible_links),
        "uncapped_eligible_links": uncapped_eligible_links,
        "weekly_max_stories_per_day": max_stories_per_day,
    }

    usage_by_model = {}
    source_quotas = normalize_source_quotas(limits_cfg.get("source_quotas"))
    ranked_candidates = []
    selected = []
    fallback_by_source: dict[str, list[dict]] = {}
    if source_quotas:
        for source_type, quota in source_quotas.items():
            source_pool = [
                item
                for item in eligible_links
                if (item.get("source_type", "") or "unknown") == source_type
            ]
            if not source_pool or quota <= 0:
                fallback_by_source[source_type] = []
                continue
            source_top_n = min(
                len(source_pool),
                max(quota, min(limits_cfg["select_top_stories"], quota * 3)),
            )
            source_ranked = select_top_stories_fn(
                source_pool,
                usage_by_model,
                source_top_n,
                openai_cfg["reasoning_model"],
                preferred_sources=preferred_sources,
            )
            ranked_candidates.extend(source_ranked)
            selected.extend(source_ranked[:quota])
            fallback_by_source[source_type] = source_ranked[quota:]

        target_story_count = sum(source_quotas.values())
        if len(selected) < target_story_count:
            selected_urls = {item.get("url", "") for item in selected}
            remaining_pool = [
                item for item in eligible_links if item.get("url", "") not in selected_urls
            ]
            needed = target_story_count - len(selected)
            if remaining_pool and needed > 0:
                fill_ranked = select_top_stories_fn(
                    remaining_pool,
                    usage_by_model,
                    needed,
                    openai_cfg["reasoning_model"],
                    preferred_sources=preferred_sources,
                )
                selected.extend(fill_ranked[:needed])
                ranked_candidates.extend(fill_ranked)
        selected = dedupe_links_by_url_fn(selected)
        selected = selected[:target_story_count]
    else:
        ranked_candidates = select_top_stories_fn(
            eligible_links,
            usage_by_model,
            limits_cfg["select_top_stories"],
            openai_cfg["reasoning_model"],
            preferred_sources=preferred_sources,
        )
        selected = post_process_selected(
            ranked_candidates,
            limits_cfg["max_per_category"],
            limits_cfg["final_top_stories"],
            {},
        )
        target_story_count = len(selected)

    if not ranked_candidates:
        emit_event(
            "pipeline_completed",
            status="no_ranked_candidates",
            ranked_candidates=0,
            selected=0,
            eligible_links=len(eligible_links),
            usage_by_model=compact_model_usage(usage_by_model),
        )
        return {
            **result,
            "status": "no_ranked_candidates",
            "ranked_candidates": 0,
            "selected": 0,
        }
    if not selected:
        emit_event(
            "pipeline_completed",
            status="no_selected_candidates",
            ranked_candidates=len(ranked_candidates),
            selected=0,
            usage_by_model=compact_model_usage(usage_by_model),
        )
        return {
            **result,
            "status": "no_selected_candidates",
            "ranked_candidates": len(ranked_candidates),
            "selected": 0,
        }

    emit_event(
        "pipeline_ranking_completed",
        ranked_candidates=len(ranked_candidates),
        selected_candidates=len(selected),
        target_story_count=target_story_count,
        source_quotas=source_quotas,
        ranked_source_type_counts=structured_counts(ranked_candidates, "source_type"),
        ranked_source_name_counts_top10=structured_counts(ranked_candidates, "source_name", top_n=10),
        selected_source_type_counts=structured_counts(selected, "source_type"),
    )

    target_story_count = min(target_story_count, len(selected))
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
        summary_block = process_story_fn(
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
        source_type = item.get("source_type", "") or "unknown"
        emit_event(
            "pipeline_candidate_skipped",
            url=item.get("url", ""),
            source_type=source_type,
            source_name=item.get("source_name", ""),
            reason="empty_fetch_or_summary",
        )
        replacement_summary = None
        replacement_item = None
        source_fallback_queue = fallback_by_source.get(source_type, [])
        while source_fallback_queue and replacement_summary is None:
            candidate = source_fallback_queue.pop(0)
            candidate_summary = process_story_fn(
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

        while fallback_candidates and replacement_summary is None:
            candidate = fallback_candidates.pop(0)
            candidate_summary = process_story_fn(
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
            emit_event(
                "pipeline_backfill_applied",
                original_url=item.get("url", ""),
                original_source_type=source_type,
                replacement_url=replacement_item.get("url", ""),
                replacement_source_type=replacement_item.get("source_type", ""),
                replacement_source_name=replacement_item.get("source_name", ""),
            )
        else:
            emit_event(
                "pipeline_backfill_unavailable",
                original_url=item.get("url", ""),
                original_source_type=source_type,
                accepted_items=len(accepted_items),
                target_story_count=target_story_count,
            )

    if not summaries:
        emit_event(
            "pipeline_completed",
            status="no_summaries",
            ranked_candidates=len(ranked_candidates),
            selected=len(selected),
            accepted_items=0,
            backfilled_count=backfilled_count,
            skipped_count=skipped_count,
            usage_by_model=compact_model_usage(usage_by_model),
        )
        return {
            **result,
            "status": "no_summaries",
            "ranked_candidates": len(ranked_candidates),
            "selected": len(selected),
            "accepted_items": 0,
            "backfilled_count": backfilled_count,
            "skipped_count": skipped_count,
        }

    emit_event(
        "pipeline_summaries_completed",
        status="completed",
        accepted_items=len(accepted_items),
        target_story_count=target_story_count,
        backfilled_count=backfilled_count,
        skipped_count=skipped_count,
        final_source_type_counts=structured_counts(accepted_items, "source_type"),
    )

    render_groups = build_render_groups_fn(summaries)
    final_text = render_digest_text_fn(render_groups)
    issue_type = str(config.get("delivery", {}).get("issue_type", "daily") or "daily")
    digest_html = _render_html_with_issue_type(
        render_digest_html_fn,
        render_groups,
        issue_type=issue_type,
    )
    email_safe_digest_html = _render_html_with_issue_type(
        render_email_safe_digest_html_fn,
        render_groups,
        issue_type=issue_type,
    )
    digest_subject = email_cfg["digest_subject"]
    final_usage_by_model = compact_model_usage(usage_by_model)
    total_tokens = sum(
        int(stats.get("total", 0) or 0)
        for stats in final_usage_by_model.values()
        if isinstance(stats, dict)
    )
    accepted_story_payloads = []
    for _, item, summary_block in summaries:
        title, url, _ = parse_summary_block(summary_block)
        accepted_story_payloads.append(
            {
                "title": title,
                "url": url or item.get("url", ""),
                "source_type": item.get("source_type", ""),
                "source_name": item.get("source_name", ""),
                "category": item.get("category", ""),
                "anchor_text": item.get("anchor_text", ""),
                "published_at": item.get("published_at", ""),
            }
        )
    emit_event(
        "pipeline_completed",
        status="completed",
        ranked_candidates=len(ranked_candidates),
        selected=len(selected),
        accepted_items=len(accepted_items),
        target_story_count=target_story_count,
        backfilled_count=backfilled_count,
        skipped_count=skipped_count,
        final_source_type_counts=structured_counts(accepted_items, "source_type"),
        final_source_name_counts_top10=structured_counts(accepted_items, "source_name", top_n=10),
        accepted_story_urls=[story["url"] for story in accepted_story_payloads],
        usage_by_model=final_usage_by_model,
        total_tokens=total_tokens,
    )
    return {
        **result,
        "status": "completed",
        "ranked_candidates": len(ranked_candidates),
        "selected": len(selected),
        "accepted_items": len(accepted_items),
        "accepted_story_items": accepted_story_payloads,
        "backfilled_count": backfilled_count,
        "skipped_count": skipped_count,
        "sent_recipients": 0,
        "digest_subject": digest_subject,
        "digest_body": final_text,
        "digest_html": digest_html,
        "email_safe_digest_html": email_safe_digest_html,
        "render_groups": render_groups,
        "usage_by_model": final_usage_by_model,
        "total_tokens": total_tokens,
    }
