from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from curator.config import load_config
from curator.jobs import get_repository_from_config
from tests.helpers import write_temp_config


def test_backfill_subscriber_default_sources_script_persists_defaults(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={"database": {"path": str(tmp_path / "curator.sqlite3")}},
    )
    config = load_config(str(config_path))
    repository = get_repository_from_config(config)

    repository.upsert_source(source_type="additional_source", source_name="OpenAI News")
    repository.upsert_source(source_type="additional_source", source_name="Macro Wire")

    first = repository.upsert_subscriber("first@example.com")
    second = repository.upsert_subscriber("second@example.com")
    third = repository.upsert_subscriber("third@example.com")

    repository.upsert_subscriber_profile(
        int(second["id"]),
        persona_text="Keep this persona.",
        delivery_format="pdf",
        preferred_sources=["Macro Wire"],
    )
    repository.upsert_subscriber_profile(
        int(third["id"]),
        preferred_sources=[],
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/backfill_subscriber_default_sources.py",
            "--config",
            str(config_path),
        ],
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout.strip())

    refreshed_repository = get_repository_from_config(load_config(str(config_path)))
    first_profile = refreshed_repository.get_subscriber_profile(int(first["id"]))
    second_profile = refreshed_repository.get_subscriber_profile(int(second["id"]))
    third_profile = refreshed_repository.get_subscriber_profile(int(third["id"]))

    assert payload["status"] == "completed"
    assert payload["default_sources"] == ["OpenAI News"]
    assert payload["created_profiles"] == 1
    assert payload["updated_profiles"] == 2
    assert first_profile["preferred_sources"] == ["OpenAI News"]
    assert second_profile["persona_text"] == "Keep this persona."
    assert second_profile["delivery_format"] == "pdf"
    assert second_profile["preferred_sources"] == ["OpenAI News", "Macro Wire"]
    assert third_profile["preferred_sources"] == ["OpenAI News"]
