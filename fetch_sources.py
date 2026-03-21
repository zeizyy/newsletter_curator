from __future__ import annotations

import json

from curator.config import load_config
from curator.jobs import run_fetch_sources_job


def main() -> None:
    config = load_config()
    result = run_fetch_sources_job(config)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
