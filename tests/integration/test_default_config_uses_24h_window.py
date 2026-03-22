from __future__ import annotations

from curator.config import DEFAULT_CONFIG, load_config
from tests.helpers import write_temp_config


def test_default_config_uses_24h_window(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "persona": {"text": "Local test persona"},
        },
    )

    config = load_config(str(config_path))

    assert DEFAULT_CONFIG["gmail"]["query_time_window"] == "newer_than:1d"
    assert DEFAULT_CONFIG["additional_sources"]["hours"] == 24
    assert config["gmail"]["query_time_window"] == "newer_than:1d"
    assert config["additional_sources"]["hours"] == 24
