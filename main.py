import os
import traceback

from openai import OpenAI

from curator import config as config_module
from curator import content, dev, gmail, llm, pipeline, rendering, sources


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


def run_job(config: dict, service) -> dict:
    from curator.jobs import run_delivery_job

    development_cfg = config.get("development", {})
    persona_text = str(config.get("persona", {}).get("text", "")).strip()
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
        else (lambda article_text, usage_by_model, lock, summary_model: summarize_article_with_llm(
            article_text,
            usage_by_model,
            lock,
            summary_model,
            persona_text=persona_text,
        ))
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

    return run_delivery_job(
        config,
        service,
        collect_gmail_links_fn=collect_gmail_links,
        collect_source_links_fn=collect_additional_source_links,
        select_top_stories_fn=select_top_stories_fn,
        process_story_fn=process_story_fn,
        group_summaries_by_category_fn=group_summaries_by_category,
        render_digest_html_fn=render_digest_html,
        send_email_fn=send_email,
    )


def main():
    config = load_config()
    service = None
    try:
        service = get_gmail_service(config["paths"])
        run_job(config, service)
    except Exception:
        error_details = traceback.format_exc()
        print(error_details)
        if service:
            try:
                send_email(
                    service,
                    to_address=config["email"]["alert_recipient"],
                    subject=f"{config['email']['alert_subject_prefix']}",
                    body=error_details,
                )
            except Exception as exc:
                print(f"Failed to send alert email: {exc}")
        raise


if __name__ == "__main__":
    main()
