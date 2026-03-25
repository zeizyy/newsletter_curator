#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from curator import config as config_module
from curator.jobs import get_repository_from_config
from curator.rendering import render_digest_html, render_email_safe_digest_html


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a local HTML and screenshot review pack for a stored newsletter."
    )
    parser.add_argument("--config-path", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--newsletter-date", default="")
    parser.add_argument(
        "--include-admin-surfaces",
        dest="include_admin_surfaces",
        action="store_true",
        default=True,
        help="Include admin /, /analytics, and /preview HTML fixtures.",
    )
    parser.add_argument(
        "--skip-admin-surfaces",
        dest="include_admin_surfaces",
        action="store_false",
        help="Only render digest HTML fixtures, without admin pages.",
    )
    parser.add_argument(
        "--thumbnail-size",
        type=int,
        default=1600,
        help="Quick Look thumbnail size passed to qlmanage.",
    )
    return parser.parse_args()


def resolve_output_dir(output_dir: Path | None) -> Path:
    if output_dir is not None:
        return output_dir.resolve()
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M%S")
    return Path(tempfile.gettempdir()).resolve() / f"newsletter_review_pack_{stamp}"


def resolve_newsletter_date(raw: str) -> str:
    value = str(raw or "").strip()
    if value:
        return value
    return dt.datetime.now(dt.UTC).date().isoformat()


def ensure_render_groups(newsletter: dict) -> dict:
    content = newsletter.get("content", {}) or {}
    metadata = newsletter.get("metadata", {}) or {}
    render_groups = content.get("render_groups") or metadata.get("render_groups", {})
    if not render_groups:
        raise RuntimeError(
            "Stored newsletter does not include render_groups, so the review pack cannot rerender it."
        )
    return render_groups


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def render_admin_pages(config_path: Path, newsletter_date: str) -> dict[str, str]:
    import admin_app

    admin_app.CONFIG_PATH = str(config_path)
    previous_current_newsletter_date = admin_app.current_newsletter_date
    admin_app.current_newsletter_date = lambda: newsletter_date
    try:
        client = admin_app.app.test_client()
        pages = {
            "admin_config.html": client.get("/").get_data(as_text=True),
            "admin_analytics.html": client.get("/analytics").get_data(as_text=True),
            "admin_preview.html": client.get("/preview").get_data(as_text=True),
        }
        return pages
    finally:
        admin_app.current_newsletter_date = previous_current_newsletter_date


def generate_screenshots(html_paths: list[Path], screens_dir: Path, *, thumbnail_size: int) -> list[Path]:
    screens_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "qlmanage",
        "-t",
        "-s",
        str(thumbnail_size),
        "-o",
        str(screens_dir),
        *[str(path) for path in html_paths],
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return [screens_dir / f"{path.name}.png" for path in html_paths]


def main() -> None:
    args = parse_args()
    config_path = (args.config_path or Path(config_module.DEFAULT_CONFIG_PATH)).resolve()
    output_dir = resolve_output_dir(args.output_dir)
    newsletter_date = resolve_newsletter_date(args.newsletter_date)

    previous_env_config = os.environ.get("NEWSLETTER_CONFIG")
    os.environ["NEWSLETTER_CONFIG"] = str(config_path)
    try:
        config = config_module.load_config(config_path)
        repository = get_repository_from_config(config)
        newsletter = repository.get_daily_newsletter(newsletter_date)
        if newsletter is None:
            raise RuntimeError(f"No stored newsletter exists for {newsletter_date}.")

        render_groups = ensure_render_groups(newsletter)
        output_dir.mkdir(parents=True, exist_ok=True)

        html_paths: list[Path] = []
        digest_market_tape_path = output_dir / "digest_market_tape.html"
        digest_email_safe_path = output_dir / "digest_email_safe.html"
        write_file(digest_market_tape_path, render_digest_html(render_groups))
        write_file(digest_email_safe_path, render_email_safe_digest_html(render_groups))
        html_paths.extend([digest_market_tape_path, digest_email_safe_path])

        if args.include_admin_surfaces:
            for filename, html in render_admin_pages(config_path, newsletter_date).items():
                html_path = output_dir / filename
                write_file(html_path, html)
                html_paths.append(html_path)

        screenshot_paths = generate_screenshots(
            html_paths,
            output_dir / "screens",
            thumbnail_size=args.thumbnail_size,
        )

        print(f"Review pack output: {output_dir}")
        print("HTML fixtures:")
        for path in html_paths:
            print(f"  {path}")
        print("Screenshots:")
        for path in screenshot_paths:
            print(f"  {path}")
    finally:
        if previous_env_config is None:
            os.environ.pop("NEWSLETTER_CONFIG", None)
        else:
            os.environ["NEWSLETTER_CONFIG"] = previous_env_config


if __name__ == "__main__":
    main()
