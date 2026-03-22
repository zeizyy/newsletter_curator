from __future__ import annotations

from curator.config import load_config


def test_default_config_includes_repo_persona():
    config = load_config("config.yaml")
    persona = str(config.get("persona", {}).get("text", "") or "")

    assert "Rank highest: stories about AI value capture" in persona
    assert "Google strategy in Search/Discover/AI Mode/Workspace" in persona
    assert "Tie each story to strategy, technical mechanism, adoption, economics" in persona
    assert "PR fluff, hype, generic macro, repetitive benchmark news, shallow summaries" in persona
