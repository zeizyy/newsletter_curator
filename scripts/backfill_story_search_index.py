from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from curator import config as config_module
from curator.repository import SQLiteRepository
from curator.story_feed import resolve_database_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the FTS5 search index for existing repository stories.",
    )
    parser.add_argument("--config-path", default=config_module.DEFAULT_CONFIG_PATH)
    args = parser.parse_args()

    config = config_module.load_config(args.config_path)
    repository = SQLiteRepository(resolve_database_path(config))
    repository.initialize()
    result = repository.rebuild_story_search_index()

    print(
        "Backfilled story search index: "
        f"{result['stories_indexed']} indexed / {result['stories_seen']} stories seen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
