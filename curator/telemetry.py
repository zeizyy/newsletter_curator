from __future__ import annotations

import html
import os
from urllib.parse import quote


TRACKING_PIXEL_TAG_MARKER = "newsletter-tracking-pixel"


def _coerce_bool(raw_value) -> bool | None:
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip():
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}
    return None


def _global_tracking_enabled(config: dict) -> bool:
    tracking_cfg = config.get("tracking", {})
    config_enabled = _coerce_bool(tracking_cfg.get("enabled"))
    if config_enabled is not None:
        return config_enabled
    env_enabled = os.getenv("CURATOR_ENABLE_TELEMETRY", "").strip()
    if env_enabled:
        return env_enabled.lower() in {"1", "true", "yes", "on"}
    return False


def open_tracking_enabled(config: dict) -> bool:
    tracking_cfg = config.get("tracking", {})
    config_enabled = _coerce_bool(tracking_cfg.get("open_enabled"))
    if config_enabled is not None:
        return config_enabled
    return _global_tracking_enabled(config)


def click_tracking_enabled(config: dict) -> bool:
    tracking_cfg = config.get("tracking", {})
    config_enabled = _coerce_bool(tracking_cfg.get("click_enabled"))
    if config_enabled is not None:
        return config_enabled
    return _global_tracking_enabled(config)


def telemetry_enabled(config: dict) -> bool:
    return open_tracking_enabled(config) or click_tracking_enabled(config)


def resolve_tracking_base_url(config: dict) -> str:
    tracking_cfg = config.get("tracking", {})
    base_url = str(tracking_cfg.get("base_url", "")).strip()
    if base_url:
        return base_url.rstrip("/")

    env_base_url = os.getenv("CURATOR_PUBLIC_BASE_URL", "").strip()
    if env_base_url:
        return env_base_url.rstrip("/")

    host = os.getenv("CURATOR_ADMIN_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.getenv("CURATOR_ADMIN_PORT", "8080").strip() or "8080"
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def build_click_url(base_url: str, click_token: str) -> str:
    return f"{base_url}/track/click/{quote(click_token)}"


def build_open_pixel_url(base_url: str, open_token: str) -> str:
    return f"{base_url}/track/open/{quote(open_token)}.gif"


def rewrite_newsletter_html_for_tracking(
    html_body: str,
    *,
    tracked_links: list[dict],
    open_pixel_url: str = "",
) -> str:
    tracked_html = html_body
    for link in tracked_links:
        target_url = str(link.get("target_url", "")).strip()
        tracked_url = str(link.get("tracked_url", "")).strip()
        if not target_url or not tracked_url:
            continue
        tracked_html = tracked_html.replace(
            f'href="{html.escape(target_url)}"',
            f'href="{html.escape(tracked_url)}"',
        )

    if not open_pixel_url:
        return tracked_html

    pixel_tag = (
        f'<img src="{html.escape(open_pixel_url)}" alt="" width="1" height="1" '
        f'style="display:block;border:0;width:1px;height:1px;opacity:0;" '
        f'class="{TRACKING_PIXEL_TAG_MARKER}" />'
    )
    if "</body>" in tracked_html:
        return tracked_html.replace("</body>", f"{pixel_tag}</body>", 1)
    return tracked_html + pixel_tag


def strip_tracking_pixel(html_body: str) -> str:
    marker = TRACKING_PIXEL_TAG_MARKER
    start = html_body.find(f'class="{marker}"')
    if start == -1:
        return html_body

    tag_start = html_body.rfind("<img", 0, start)
    tag_end = html_body.find(">", start)
    if tag_start == -1 or tag_end == -1:
        return html_body
    return html_body[:tag_start] + html_body[tag_end + 1 :]
