import traceback

from openai import OpenAI

from curator.alerts import send_delivery_failure_alert_if_needed as _send_delivery_failure_alert_if_needed
from curator import config as config_module
from curator import content, dev, gmail, llm, pipeline, rendering, sources
from curator.telemetry import (
    click_tracking_enabled as click_tracking_enabled_for_config,
    open_tracking_enabled as open_tracking_enabled_for_config,
)


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


def send_delivery_failure_alert_if_needed(
    config: dict,
    service,
    *,
    source: str,
    result: dict | None = None,
    exception: Exception | None = None,
    traceback_text: str = "",
) -> bool:
    return _send_delivery_failure_alert_if_needed(
        config,
        service,
        send_email_fn=send_email,
        source=source,
        result=result,
        exception=exception,
        traceback_text=traceback_text,
    )


def select_top_stories(
    items: list[dict],
    usage_by_model: dict,
    top_stories: int,
    reasoning_model: str,
    *,
    persona_text: str = "",
    preferred_sources: list[str] | tuple[str, ...] | None = None,
) -> list[dict]:
    return llm.select_top_stories(
        items,
        usage_by_model,
        top_stories,
        reasoning_model,
        persona_text=persona_text,
        preferred_sources=preferred_sources,
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
    return sources.collect_repository_source_links(config, base_dir=config_module.BASE_DIR)


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


def run_job(config: dict, service, *, recipient_override: str | None = None) -> dict:
    return _run_delivery(
        config,
        service,
        send_email_fn=send_email,
        recipient_override=recipient_override,
    )


def preview_job(config: dict) -> dict:
    captured_messages: list[dict] = []

    def capture_send_email(
        service,
        to_address: str,
        subject: str,
        body: str,
        html_body: str | None = None,
        attachments: list[dict] | None = None,
        message_id_header: str = "",
    ):
        captured_messages.append(
            {
                "to": to_address,
                "subject": subject,
                "body": body,
                "html_body": html_body or "",
                "attachments": list(attachments or []),
                "message_id_header": message_id_header,
            }
        )

    result = _run_delivery(config, service=None, send_email_fn=capture_send_email)
    preview = captured_messages[0] if captured_messages else None
    return {**result, "preview": preview}


def _run_delivery(config: dict, service, *, send_email_fn, recipient_override: str | None = None) -> dict:
    from curator.jobs import (
        DEFAULT_AUDIENCE_KEY,
        current_delivery_datetime,
        delivery_schedule_ignored,
        delivery_issue_type_for_datetime,
        get_repository_from_config,
        group_delivery_subscribers,
        resolve_delivery_subscribers,
        run_delivery_job,
    )

    development_cfg = config.get("development", {})
    default_persona_text = str(config.get("persona", {}).get("text", "")).strip()
    repository = get_repository_from_config(config)
    if (
        service is not None
        and not delivery_schedule_ignored()
        and delivery_issue_type_for_datetime(current_delivery_datetime()) == "skipped"
    ):
        skipped_result = run_delivery_job(
            config,
            service,
            repository=repository,
            send_email_fn=send_email_fn,
        )
        return {**skipped_result, "delivery_subscribers": []}

    subscribers, recipient_source = resolve_delivery_subscribers(
        config,
        repository=repository,
        recipient_override=recipient_override,
    )
    delivery_subscribers = [
        {
            "email": str(subscriber.get("email", "")).strip().lower(),
            "persona_text": str(subscriber.get("persona_text", "")).strip(),
            "delivery_format": str(subscriber.get("delivery_format", "email")).strip() or "email",
            "preferred_sources": list(subscriber.get("preferred_sources") or []),
            "profile_key": str(subscriber.get("profile_key", "")).strip(),
        }
        for subscriber in subscribers
    ]

    def run_profile_delivery(
        *,
        persona_text: str,
        delivery_format: str,
        preferred_sources: list[str],
        recipients: list[str],
        use_cached_newsletter: bool,
        persist_newsletter: bool,
        audience_key: str,
    ) -> dict:
        select_top_stories_fn = (
            (lambda items, usage_by_model, top_stories, reasoning_model, *, preferred_sources=None: dev.fake_select_top_stories(
                items,
                usage_by_model,
                top_stories,
                reasoning_model,
                persona_text=persona_text,
                preferred_sources=preferred_sources,
            ))
            if development_cfg.get("fake_inference", False)
            else (lambda items, usage_by_model, top_stories, reasoning_model, *, preferred_sources=None: select_top_stories(
                items,
                usage_by_model,
                top_stories,
                reasoning_model,
                persona_text=persona_text,
                preferred_sources=preferred_sources,
            ))
        )
        summarize_fn = (
            (lambda article_text, usage_by_model, lock, summary_model: dev.fake_summarize_article(
                article_text,
                usage_by_model,
                lock,
                summary_model,
            ))
            if development_cfg.get("fake_inference", False)
            else (
                lambda article_text, usage_by_model, lock, summary_model: summarize_article_with_llm(
                    article_text,
                    usage_by_model,
                    lock,
                    summary_model,
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
            return collect_gmail_links(cfg, svc)

        def collect_profile_source_links(cfg):
            return collect_additional_source_links(cfg)

        return run_delivery_job(
            config,
            service,
            repository=repository,
            collect_gmail_links_fn=collect_profile_gmail_links,
            collect_source_links_fn=collect_profile_source_links,
            select_top_stories_fn=select_top_stories_fn,
            process_story_fn=process_story_fn,
            group_summaries_by_category_fn=group_summaries_by_category,
            render_digest_html_fn=render_digest_html,
            send_email_fn=send_email_fn,
            resolve_digest_recipients_fn=lambda cfg: (list(recipients), recipient_source),
            open_tracking_enabled=service is not None and open_tracking_enabled_for_config(config),
            click_tracking_enabled=service is not None and click_tracking_enabled_for_config(config),
            use_cached_newsletter=use_cached_newsletter,
            persist_newsletter=persist_newsletter,
            audience_key=audience_key,
            delivery_format=delivery_format,
            preferred_sources=preferred_sources,
        )

    personalized_delivery = service is not None and any(
        subscriber["persona_text"] != default_persona_text
        or subscriber["preferred_sources"]
        or subscriber["delivery_format"] != "email"
        for subscriber in subscribers
    )
    if not personalized_delivery:
        profile_result = run_profile_delivery(
            persona_text=default_persona_text,
            delivery_format="email",
            preferred_sources=[],
            recipients=[subscriber["email"] for subscriber in subscribers],
            use_cached_newsletter=True,
            persist_newsletter=True,
            audience_key=DEFAULT_AUDIENCE_KEY,
        )
        return {
            **profile_result,
            "delivery_subscribers": delivery_subscribers,
        }

    delivery_groups = group_delivery_subscribers(subscribers)
    group_results: list[dict] = []
    total_sent_recipients = 0
    total_failed_recipients = 0
    group_statuses: list[str] = []
    for group in delivery_groups:
        profile_result = run_profile_delivery(
            persona_text=group["persona_text"],
            delivery_format=group["delivery_format"],
            preferred_sources=group["preferred_sources"],
            recipients=group["recipients"],
            use_cached_newsletter=True,
            persist_newsletter=True,
            audience_key=group["audience_key"],
        )
        group_status = str(profile_result.get("status", "")).strip() or "unknown"
        group_statuses.append(group_status)
        total_sent_recipients += int(profile_result.get("sent_recipients", 0) or 0)
        total_failed_recipients += int(profile_result.get("failed_recipient_count", 0) or 0)
        group_results.append(
            {
                "profile_key": group["profile_key"],
                "audience_key": str(profile_result.get("audience_key", "")).strip(),
                "persona_text": group["persona_text"],
                "delivery_format": group["delivery_format"],
                "preferred_sources": group["preferred_sources"],
                "recipients": group["recipients"],
                "sent_recipients": int(profile_result.get("sent_recipients", 0) or 0),
                "failed_recipient_count": int(profile_result.get("failed_recipient_count", 0) or 0),
                "failed_recipients": list(profile_result.get("failed_recipients", []) or []),
                "status": group_status,
                "cached_newsletter": bool(profile_result.get("cached_newsletter", False)),
                "daily_newsletter_id": profile_result.get("daily_newsletter_id"),
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
        "cached_newsletter": all(
            bool(group_result.get("cached_newsletter", False)) for group_result in group_results
        ),
        "recipient_source": recipient_source,
        "sent_recipients": total_sent_recipients,
        "failed_recipient_count": total_failed_recipients,
        "delivery_subscribers": delivery_subscribers,
        "delivery_groups": group_results,
    }


def main():
    config = load_config()
    service = None
    try:
        service = get_gmail_service(config["paths"])
        result = run_job(config, service)
        try:
            send_delivery_failure_alert_if_needed(
                config,
                service,
                source="main.py",
                result=result,
            )
        except Exception as alert_exc:
            print(f"Failed to send alert email: {alert_exc}")
    except Exception as exc:
        error_details = traceback.format_exc()
        print(error_details)
        try:
            send_delivery_failure_alert_if_needed(
                config,
                service,
                source="main.py",
                exception=exc,
                traceback_text=error_details,
            )
        except Exception as alert_exc:
            print(f"Failed to send alert email: {alert_exc}")
        raise


if __name__ == "__main__":
    main()
