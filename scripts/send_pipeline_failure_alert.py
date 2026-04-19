from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main as delivery_main
from curator.alerts import delivery_failure_requires_alert


OUTPUT_TAIL_LINES = 120


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send a failure alert for the generated daily pipeline wrapper."
    )
    parser.add_argument("--source", default="run_daily_pipeline.sh")
    parser.add_argument("--exit-status", type=int, required=True)
    parser.add_argument("--output-file", required=True)
    return parser.parse_args(argv)


def read_output_tail(output_file: str, *, lines: int = OUTPUT_TAIL_LINES) -> str:
    path = Path(output_file)
    if not path.exists():
        return f"Pipeline output file was not found: {path}"
    output_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = output_lines[-lines:]
    if len(output_lines) > len(tail):
        return f"Pipeline output tail, last {len(tail)} of {len(output_lines)} lines:\n" + "\n".join(tail)
    return "Pipeline output:\n" + "\n".join(tail)


def load_result_from_output(output_file: str) -> dict | None:
    path = Path(output_file)
    if not path.exists():
        return None
    output_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for index, line in enumerate(output_lines):
        if not line.strip().startswith("{"):
            continue
        candidate = "\n".join(output_lines[index:])
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = delivery_main.load_config()
    result = load_result_from_output(args.output_file)
    if result is not None and not delivery_failure_requires_alert(result):
        return
    service = delivery_main.get_gmail_service(config["paths"])
    exception = RuntimeError(f"daily pipeline exited with status {args.exit_status}")
    sent = delivery_main.send_delivery_failure_alert_if_needed(
        config,
        service,
        source=str(args.source or "run_daily_pipeline.sh").strip() or "run_daily_pipeline.sh",
        result=result,
        exception=exception,
        traceback_text=read_output_tail(args.output_file),
    )
    if not sent:
        raise SystemExit("failure alert was skipped; check email.alert_recipient and Gmail service setup")


if __name__ == "__main__":
    main()
