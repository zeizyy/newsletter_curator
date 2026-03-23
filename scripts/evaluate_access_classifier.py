from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from curator.config import load_config
from curator.evaluation import (
    export_evaluation_candidates,
    load_labels_file,
    replay_classifier_against_evaluation,
    report_access_evaluations,
    store_agent_evaluation,
)
from curator.jobs import get_repository_from_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export repository stories for Codex review or persist Codex labels."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the curator config file.",
    )
    parser.add_argument(
        "--source-type",
        default=None,
        help="Optional source_type filter for export mode.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of stories to export for evaluation.",
    )
    parser.add_argument(
        "--labels-file",
        default="",
        help="JSON file containing Codex labels to persist. If omitted, the script exports candidates.",
    )
    parser.add_argument(
        "--evaluator",
        default="codex",
        help="Evaluator name to store with the evaluation run.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print recent evaluation runs and confusion-matrix metrics instead of exporting candidates.",
    )
    parser.add_argument(
        "--report-limit",
        type=int,
        default=10,
        help="Maximum number of evaluation runs to include in report mode.",
    )
    parser.add_argument(
        "--replay-run-id",
        type=int,
        default=0,
        help="Replay the current classifier against a stored evaluation run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    repository = get_repository_from_config(config)

    if args.replay_run_id:
        print(
            json.dumps(
                replay_classifier_against_evaluation(
                    repository,
                    evaluation_run_id=args.replay_run_id,
                ),
                indent=2,
            )
        )
        return

    if args.report:
        print(json.dumps(report_access_evaluations(repository, limit=args.report_limit), indent=2))
        return

    if args.labels_file:
        labels = load_labels_file(Path(args.labels_file))
        result = store_agent_evaluation(
            repository,
            labels=labels,
            evaluator=args.evaluator,
            scope={"source_type": args.source_type, "limit": args.limit},
        )
        print(json.dumps(result, sort_keys=True))
        return

    payload = export_evaluation_candidates(
        repository,
        limit=args.limit,
        source_type=args.source_type,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
