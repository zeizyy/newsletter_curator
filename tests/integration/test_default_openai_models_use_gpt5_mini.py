from __future__ import annotations

from curator.config import DEFAULT_CONFIG, load_config
from tests.helpers import write_temp_config


def test_default_openai_models_use_gpt5_mini(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "persona": {"text": "Local test persona"},
        },
    )

    config = load_config(str(config_path))

    assert DEFAULT_CONFIG["openai"]["reasoning_model"] == "gpt-5-mini"
    assert DEFAULT_CONFIG["openai"]["summary_model"] == "gpt-5-mini"
    assert config["openai"]["reasoning_model"] == "gpt-5-mini"
    assert config["openai"]["summary_model"] == "gpt-5-mini"


def test_load_config_upgrades_legacy_gpt4o_mini_reasoning_model(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "persona": {"text": "Local test persona"},
            "openai": {"reasoning_model": "gpt-4o-mini", "summary_model": "gpt-5-mini"},
        },
    )

    config = load_config(str(config_path))

    assert config["openai"]["reasoning_model"] == "gpt-5-mini"
    assert config["openai"]["summary_model"] == "gpt-5-mini"


def test_load_config_preserves_explicit_non_legacy_reasoning_model(tmp_path):
    config_path = write_temp_config(
        tmp_path,
        overrides={
            "database": {"path": str(tmp_path / "curator.sqlite3")},
            "persona": {"text": "Local test persona"},
            "openai": {"reasoning_model": "gpt-4.1-mini", "summary_model": "gpt-5-mini"},
        },
    )

    config = load_config(str(config_path))

    assert config["openai"]["reasoning_model"] == "gpt-4.1-mini"
    assert config["openai"]["summary_model"] == "gpt-5-mini"
