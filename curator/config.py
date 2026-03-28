from __future__ import annotations

import os
from pathlib import Path

import yaml


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = os.getenv("NEWSLETTER_CONFIG", "config.yaml")
DIGEST_TEMPLATE_PATH = BASE_DIR / "templates" / "digest.html"
EMAIL_SAFE_DIGEST_TEMPLATE_PATH = BASE_DIR / "templates" / "digest_email_safe.html"
DEFAULT_CONFIG = {
    "gmail": {"label": "Newsletters", "query_time_window": "newer_than:1d"},
    "paths": {"credentials": "secrets/credentials.json", "token": "secrets/token.json"},
    "database": {
        "path": "data/newsletter_curator.sqlite3",
        "ttl_days": 7,
        "newsletter_ttl_days": 7,
        "allow_schema_reset": False,
    },
    "development": {
        "use_canned_sources": False,
        "canned_sources_file": "tests/fixtures/canned_sources.json",
        "fake_inference": False,
    },
    "persona": {"text": ""},
    "additional_sources": {
        "enabled": False,
        "script_path": "skills/daily-news-curator/scripts/build_daily_digest.py",
        "feeds_file": "",
        "hours": 24,
        "top_per_category": 5,
        "max_total": 30,
    },
    "openai": {"reasoning_model": "gpt-5-mini", "summary_model": "gpt-5-mini"},
    "limits": {
        "max_links_per_email": 15,
        "select_top_stories": 20,
        "max_per_category": 3,
        "final_top_stories": 15,
        "source_quotas": {"gmail": 10, "additional_source": 5},
        "max_article_chars": 6000,
        "article_fetch_timeout": 15,
        "article_fetch_retries": 2,
        "max_fetch_workers": 5,
        "max_summary_workers": 5,
        "max_ingest_summaries": 20,
        "max_gmail_fetch_after_score": 18,
    },
    "email": {
        "digest_recipients": [],
        "digest_subject": "Daily Newsletter Digest",
        "alert_recipient": "",
        "alert_subject_prefix": "[ALERT] Newsletter Curator Failure",
    },
    "tracking": {
        "enabled": False,
        "base_url": os.getenv("CURATOR_PUBLIC_BASE_URL", "").strip(),
    },
}


def merge_dicts(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_openai_config(config: dict) -> dict:
    openai_cfg = config.setdefault("openai", {})
    if str(openai_cfg.get("reasoning_model", "")).strip() == "gpt-4o-mini":
        openai_cfg["reasoning_model"] = "gpt-5-mini"
    return config


def load_config(config_path: str | os.PathLike[str] | None = None) -> dict:
    resolved_path = Path(config_path or DEFAULT_CONFIG_PATH)
    if not resolved_path.exists():
        return normalize_openai_config(dict(DEFAULT_CONFIG))
    with resolved_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return normalize_openai_config(merge_dicts(DEFAULT_CONFIG, data))
