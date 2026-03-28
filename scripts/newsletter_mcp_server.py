from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from curator.mcp_server import run_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Newsletter Curator MCP server over newline-delimited stdio JSON-RPC. "
            "The server is read-only and serves stored recent-story metadata from the existing SQLite repository."
        )
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help=(
            "Path to the config YAML to use when resolving the SQLite repository. "
            "Defaults to NEWSLETTER_CONFIG when set, otherwise config.yaml."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_server(config_path=args.config_path)


if __name__ == "__main__":
    raise SystemExit(main())
