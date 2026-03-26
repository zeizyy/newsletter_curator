import os
import traceback

from openai import OpenAI

from curator import config as config_module
from curator import content, dev, gmail, llm, pipeline, rendering, sources
from curator.telemetry import telemetry_enabled as telemetry_enabled_for_config


CONFIG_PATH = config_module.DEFAULT_CONFIG_PATH
DIGEST_TEMPLATE_PATH = str(config_module.DIGEST_TEMPLATE_PATH)
DEFAULT_CONFIG = config_module.DEFAULT_CONFIG


def merge_dicts(base: dict, override: dict) -> dict:
    return config_module.merge_dicts(base, override)


def load_config() -> dict:
    return config_module.load_config(CONFIG_PATH)


load_credentials = gmail.load_credentials
get_gmail_service = gmail.get_gmail_service
list_message_ids_for_label = gmail.list_message_ids_for_label
get_message = gmail.get_message
decode_base64url = gmail.decode_base64url
walk_parts = gmail.walk_parts
extract_bodies = gmail.extract_bodies
get_header_value = gmail.get_header_value
get_label_id = gmail.get_label_id
collect_live_gmail_links = gmail.collect_live_gmail_links
collect_repository_gmail_links = gmail.collect_repository_gmail_links
send_email = gmail.send_email
send_email_to_recipients = gmail.send_email_to_recipients

normalize_whitespace = content.normalize_whitespace
trim_context = content.trim_context
is_non_article_link = content.is_non_article_link
extract_links_from_html = content.extract_links_from_html
fetch_article_text = content.fetch_article_text
dedupe_links_by_url = content.dedupe_links_by_url

format_links_for_llm = llm.format_links_for_llm
parse_index_list = llm.parse_index_list
parse_selection_items = llm.parse_selection_items
extract_summary_json = llm.extract_summary_json

group_summaries_by_category = rendering.group_summaries_by_category
parse_summary_block = rendering.parse_summary_block
render_summary_body_html = rendering.render_summary_body_html
render_digest_html = rendering.render_digest_html

post_process_selected = pipeline.post_process_selected
normalize_source_quotas = pipeline.normalize_source_quotas
format_counts = pipeline.format_counts


def select_top_stories(
    items: list[dict],
    usage_by_model: dict,
    top_stories: int,
    reasoning_model: str,
    *,
    persona_text: str = "",
) -> list[dict]:
    return llm.select_top_stories(
        items,
        usage_by_model,
        top_stories,
        reasoning_model,
        persona_text=persona_text,
        client_factory=OpenAI,
    )


def summarize_article_with_llm(
    article_text: str,
    usage_by_model: dict,
    lock,
    summary_model: str,
    *,
    persona_text: str = "",
) -> str:
    return llm.summarize_article_with_llm(
        article_text,
        usage_by_model,
        lock,
        summary_model,
        persona_text=persona_text,
        client_factory=OpenAI,
    )


def collect_additional_source_links(config: dict) -> list[dict]:
    return sources.collect_repository_source_links(config, base_dir=os.path.dirname(__file__))


def collect_gmail_links(config: dict, service) -> list[dict]:
    from curator.jobs import get_repository_from_config

    repository = get_repository_from_config(config)
    return collect_repository_gmail_links(config, repository=repository)


def process_story(
    item: dict,
    usage_by_model: dict,
    lock,
    max_article_chars: int,
    summary_model: str,
) -> str | None:
    return pipeline.process_story(
        item,
        usage_by_model,
        lock,
        max_article_chars,
        summary_model,
        article_fetcher=fetch_article_text,
        summarize_article_with_llm_fn=summarize_article_with_llm,
    )


def _filter_links_by_preferred_sources(
    links: list[dict],
    preferred_sources: list[str],
) -> list[dict]:
    normalized_sources = {
        str(source).strip().lower()
        for source in preferred_sources
        if str(source).strip()
    }
    if not normalized_sources:
        return links
    return [
        item
        for item in links
        if str(item.get("source_name", "")).strip().lower() in normalized_sources
    ]


def run_job(config: dict, service, *, recipient_override: str | None = None) -> dict:
    return _run_delivery(
        config,
        service,
        send_email_fn=send_email,
        recipient_override=recipient_override,
    )


def preview_job(config: dict) -> dict:
    captured_messages: list[dict] = []

    def capture_send_email(service, to_address: str, subject: str, body: str, html_body: str | None = None):
        captured_messages.append(
            {
                "to": to_address,
                "subject": subject,
                "body": body,
                "html_body": html_body or "",
            }
        )

    result = _run_delivery(config, service=None, send_email_fn=capture_send_email)
    preview = captured_messages[0] if captured_messages else None
    return {**result, "preview": preview}


def _run_delivery(config: dict, service, *, send_email_fn, recipient_override: str | None = None) -> dict:
    from curator.jobs import (
        group_delivery_subscribers,
        resolve_delivery_subscribers,
        run_delivery_job,
    )

    development_cfg = config.get("development", {})
    default_persona_text = str(config.get("persona", {}).get("text", "")).strip()
    subscribers, recipient_source = resolve_delivery_subscribers(
        config,
        recipient_override=recipient_override,
    )

    def run_profile_delivery(
        *,
        persona_text: str,
        preferred_sources: list[str],
        recipients: list[str],
        use_cached_newsletter: bool,
        persist_newsletter: bool,
    ) -> dict:
        select_top_stories_fn = (
            (lambda items, usage_by_model, top_stories, reasoning_model: dev.fake_select_top_stories(
                items,
                usage_by_model,
                top_stories,
                reasoning_model,
                persona_text=persona_text,
            ))
            if development_cfg.get("fake_inference", False)
            else (lambda items, usage_by_model, top_stories, reasoning_model: select_top_stories(
                items,
                usage_by_model,
                top_stories,
                reasoning_model,
                persona_text=persona_text,
            ))
        )
        summarize_fn = (
            (lambda article_text, usage_by_model, lock, summary_model: dev.fake_summarize_article(
                article_text,
                usage_by_model,
                lock,
                summary_model,
                persona_text=persona_text,
            ))
            if development_cfg.get("fake_inference", False)
            else (
                lambda article_text, usage_by_model, lock, summary_model: summarize_article_with_llm(
                    article_text,
                    usage_by_model,
                    lock,
                    summary_model,
                    persona_text=persona_text,
                )
            )
        )

        def process_story_fn(item, usage_by_model, lock, max_article_chars, summary_model):
            return pipeline.process_story(
                item,
                usage_by_model,
                lock,
                max_article_chars,
                summary_model,
                article_fetcher=lambda url, chars, timeout=25, retries=3: "",
                summarize_article_with_llm_fn=summarize_fn,
            )

        def collect_profile_gmail_links(cfg, svc):
            return _filter_links_by_preferred_sources(
                collect_gmail_links(cfg, svc),
                preferred_sources,
            )

        def collect_profile_source_links(cfg):
            return _filter_links_by_preferred_sources(
                collect_additional_source_links(cfg),
                preferred_sources,
            )

        return run_delivery_job(
            config,
            service,
            collect_gmail_links_fn=collect_profile_gmail_links,
            collect_source_links_fn=collect_profile_source_links,
            select_top_stories_fn=select_top_stories_fn,
            process_story_fn=process_story_fn,
            group_summaries_by_category_fn=group_summaries_by_category,
            render_digest_html_fn=render_digest_html,
            send_email_fn=send_email_fn,
            resolve_digest_recipients_fn=lambda cfg: (list(recipients), recipient_source),
            telemetry_enabled=service is not None and telemetry_enabled_for_config(config),
            use_cached_newsletter=use_cached_newsletter,
            persist_newsletter=persist_newsletter,
        )

    personalized_delivery = service is not None and any(
        subscriber["persona_text"] != default_persona_text or subscriber["preferred_sources"]
        for subscriber in subscribers
    )
    if not personalized_delivery:
        return run_profile_delivery(
            persona_text=default_persona_text,
            preferred_sources=[],
            recipients=[subscriber["email"] for subscriber in subscribers],
            use_cached_newsletter=True,
            persist_newsletter=True,
        )

    delivery_groups = group_delivery_subscribers(subscribers)
    group_results: list[dict] = []
    total_sent_recipients = 0
    group_statuses: list[str] = []
    for group in delivery_groups:
        profile_result = run_profile_delivery(
            persona_text=group["persona_text"],
            preferred_sources=group["preferred_sources"],
            recipients=group["recipients"],
            use_cached_newsletter=False,
            persist_newsletter=False,
        )
        group_status = str(profile_result.get("status", "")).strip() or "unknown"
        group_statuses.append(group_status)
        total_sent_recipients += int(profile_result.get("sent_recipients", 0) or 0)
        group_results.append(
            {
                "profile_key": group["profile_key"],
                "persona_text": group["persona_text"],
                "preferred_sources": group["preferred_sources"],
                "recipients": group["recipients"],
                "sent_recipients": int(profile_result.get("sent_recipients", 0) or 0),
                "status": group_status,
                "digest_subject": str(profile_result.get("digest_subject", "")).strip(),
                "digest_body": str(profile_result.get("digest_body", "")).strip(),
            }
        )

    overall_status = "completed"
    if any(status != "completed" for status in group_statuses):
        non_completed = [status for status in group_statuses if status != "completed"]
        overall_status = (
            non_completed[0]
            if len(non_completed) == len(group_statuses) and len(set(non_completed)) == 1
            else "partial_failure"
        )

    return {
        "status": overall_status,
        "personalized_delivery": True,
        "cached_newsletter": False,
        "recipient_source": recipient_source,
        "sent_recipients": total_sent_recipients,
        "delivery_groups": group_results,
    }


def main():
    config = load_config()
    service = None
    try:
        service = get_gmail_service(config["paths"])
        run_job(config, service)
    except Exception:
        error_details = traceback.format_exc()
        print(error_details)
        alert_recipient = str(config.get("email", {}).get("alert_recipient", "")).strip()
        if service and alert_recipient:
            try:
                send_email(
                    service,
                    to_address=alert_recipient,
                    subject=f"{config['email']['alert_subject_prefix']}",
                    body=error_details,
                )
            except Exception as exc:
                print(f"Failed to send alert email: {exc}")
        raise


if __name__ == "__main__":
    main()
