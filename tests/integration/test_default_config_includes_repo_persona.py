from __future__ import annotations

from curator.config import load_config


def test_default_config_includes_repo_persona():
    config = load_config("config.yaml")
    persona = str(config.get("persona", {}).get("text", "") or "")

    assert "My preference in order:" in persona
    assert "Major AI industry developments & tech company news" in persona
    assert "Markets/stocks/macro/economy" in persona
    assert "Tech blogs" in persona
    assert "Interesting datapoints & anomalies" in persona
