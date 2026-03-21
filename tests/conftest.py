from __future__ import annotations

import socket
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*args, **kwargs):
        raise AssertionError("Network access is disabled in tests. Use fixtures and fakes.")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent
