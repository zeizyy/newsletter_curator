from __future__ import annotations

import socket
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-agent-evals",
        action="store_true",
        default=False,
        help="run opt-in agent eval tests that call real model APIs",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-agent-evals"):
        return
    skip_agent_eval = pytest.mark.skip(reason="requires --run-agent-evals")
    for item in items:
        if "agent_eval" in item.keywords:
            item.add_marker(skip_agent_eval)


@pytest.fixture(autouse=True)
def block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if "agent_eval" in request.node.keywords and request.config.getoption("--run-agent-evals"):
        monkeypatch.setenv("CURATOR_IGNORE_DELIVERY_SCHEDULE", "1")
        return

    def deny(*args, **kwargs):
        raise AssertionError("Network access is disabled in tests. Use fixtures and fakes.")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setenv("CURATOR_IGNORE_DELIVERY_SCHEDULE", "1")


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent
