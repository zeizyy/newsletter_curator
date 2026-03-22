from __future__ import annotations

import json

import main as delivery_main
from curator.jobs import get_repository_from_config, run_daily_orchestrator_job


def main() -> None:
    config = delivery_main.load_config()
    repository = get_repository_from_config(config)
    service = delivery_main.get_gmail_service(config["paths"])
    result = run_daily_orchestrator_job(
        config,
        service,
        repository=repository,
        delivery_runner_fn=delivery_main.run_job,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
