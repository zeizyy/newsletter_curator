from __future__ import annotations

import json

import main as delivery_main


def main() -> None:
    config = delivery_main.load_config()
    service = delivery_main.get_gmail_service(config["paths"])
    result = delivery_main.run_job(config, service)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
