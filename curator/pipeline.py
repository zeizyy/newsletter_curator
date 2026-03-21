from __future__ import annotations

from collections import Counter
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
from .rendering import group_summaries_by_category, render_digest_html
from .sources import collect_additional_source_links


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
    article_text = str(item.get("article_text", "") or "").strip()
    if not article_text:
        article_text = article_fetcher(item.get("url", ""), max_article_chars)
    if not article_text:
        return None
    summary = summarize_article_with_llm_fn(article_text, usage_by_model, lock, summary_model)
    headline, body = extract_summary_json(summary)
    if not body.strip() or body.strip() == "No article text available.":
        return None
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


def format_counts(
    items: list[dict], field: str, top_n: int | None = None, missing_label: str = "unknown"
) -> str:
    counts = Counter((str(item.get(field, "")).strip() or missing_label) for item in items)
    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    if top_n is not None:
        ordered = ordered[:top_n]
    return ", ".join(f"{name}={count}" for name, count in ordered) if ordered else "none"


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
    render_digest_html_fn=render_digest_html,
    send_email_fn=send_email,
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
    print(f"Found {len(gmail_links)} gmail candidate links for query: {query}")

    all_links = list(gmail_links)
    gmail_links_count = len(gmail_links)
    source_links = collect_additional_source_links_fn(config)
    all_links.extend(source_links)
    all_links = dedupe_links_by_url_fn(all_links)
    print("\n=== Pipeline Stats ===")
    print(f"messages_retrieved: gmail_links={len(gmail_links)}")
    print(f"links_retrieved: gmail={gmail_links_count}, additional_sources={len(source_links)}")
    print(f"links_merged_deduped: total={len(all_links)}")
    print(f"links_by_source_type: {format_counts(all_links, 'source_type')}")
    print(f"links_by_source_name_top10: {format_counts(all_links, 'source_name', top_n=10)}")

    result = {
        "status": "running",
        "gmail_links": len(gmail_links),
        "additional_source_links": len(source_links),
        "deduped_links": len(all_links),
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
                for item in all_links
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
            )
            ranked_candidates.extend(source_ranked)
            selected.extend(source_ranked[:quota])
            fallback_by_source[source_type] = source_ranked[quota:]

        target_story_count = sum(source_quotas.values())
        if len(selected) < target_story_count:
            selected_urls = {item.get("url", "") for item in selected}
            remaining_pool = [
                item for item in all_links if item.get("url", "") not in selected_urls
            ]
            needed = target_story_count - len(selected)
            if remaining_pool and needed > 0:
                fill_ranked = select_top_stories_fn(
                    remaining_pool,
                    usage_by_model,
                    needed,
                    openai_cfg["reasoning_model"],
                )
                selected.extend(fill_ranked[:needed])
                ranked_candidates.extend(fill_ranked)
        selected = dedupe_links_by_url_fn(selected)
        selected = selected[:target_story_count]
    else:
        ranked_candidates = select_top_stories_fn(
            all_links,
            usage_by_model,
            limits_cfg["select_top_stories"],
            openai_cfg["reasoning_model"],
        )
        selected = post_process_selected(
            ranked_candidates,
            limits_cfg["max_per_category"],
            limits_cfg["final_top_stories"],
            {},
        )
        target_story_count = len(selected)

    if not ranked_candidates:
        print("No top stories selected.")
        return {**result, "status": "no_ranked_candidates", "ranked_candidates": 0, "selected": 0}
    if not selected:
        print("No stories selected after ranking/quotas.")
        return {
            **result,
            "status": "no_selected_candidates",
            "ranked_candidates": len(ranked_candidates),
            "selected": 0,
        }

    print(f"ranked_selected: total={len(ranked_candidates)}")
    print(f"ranked_by_source_type: {format_counts(ranked_candidates, 'source_type')}")
    print(
        f"ranked_by_source_name_top10: {format_counts(ranked_candidates, 'source_name', top_n=10)}"
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
        replacement_summary = None
        replacement_item = None
        source_type = item.get("source_type", "") or "unknown"
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

    print(f"summaries_completed: total={len(accepted_items)} target={target_story_count}")
    print(f"summaries_backfilled: {backfilled_count}")
    print(f"summaries_skipped_fetch_or_empty: {skipped_count}")
    if not summaries:
        print("No stories could be summarized after fetch/filter checks.")
        return {
            **result,
            "status": "no_summaries",
            "ranked_candidates": len(ranked_candidates),
            "selected": len(selected),
            "accepted_items": 0,
            "backfilled_count": backfilled_count,
            "skipped_count": skipped_count,
        }

    print(f"returned_final: total={len(accepted_items)}")
    print(f"final_by_source_type: {format_counts(accepted_items, 'source_type')}")
    print(
        f"final_by_source_name_top10: {format_counts(accepted_items, 'source_name', top_n=10)}"
    )

    grouped = group_summaries_by_category_fn(summaries)
    sections = []
    for category, entries in grouped.items():
        section_text = [category, ""]
        section_text.extend(entries)
        sections.append("\n\n".join(section_text))
    final_text = "\n\n===\n\n".join(sections)

    if usage_by_model:
        print("\n=== Token Usage ===")
        for model_name, stats in usage_by_model.items():
            print(
                f"{model_name}: input={stats['input']} output={stats['output']} total={stats['total']}"
            )

    digest_html = render_digest_html_fn(grouped)
    for recipient in email_cfg["digest_recipients"]:
        send_email_fn(
            service,
            to_address=recipient,
            subject=email_cfg["digest_subject"],
            body=final_text,
            html_body=digest_html,
        )
    return {
        **result,
        "status": "completed",
        "ranked_candidates": len(ranked_candidates),
        "selected": len(selected),
        "accepted_items": len(accepted_items),
        "backfilled_count": backfilled_count,
        "skipped_count": skipped_count,
        "sent_recipients": len(email_cfg["digest_recipients"]),
    }
