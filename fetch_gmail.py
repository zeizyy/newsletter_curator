from __future__ import annotations

import json

from curator.config import load_config
from curator.gmail import get_gmail_service
from curator.jobs import run_fetch_gmail_job


def main() -> None:
    config = load_config()
    service = get_gmail_service(config["paths"])
    result = run_fetch_gmail_job(config, service)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
