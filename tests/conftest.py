"""Gemeinsame pytest-Fixtures für die Backend-Tests."""
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from attrappen import fake_getaddrinfo  # noqa: E402


@pytest.fixture
def fake_dns(monkeypatch):
    """Kein echtes DNS: nur die Namen aus attrappen.FAKE_DNS lösen auf.
    Gibt die Liste der abgefragten Namen zurück."""
    aufrufe = []
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo(aufrufe))
    return aufrufe


@pytest.fixture
def keine_pausen(monkeypatch):
    """Ersetzt asyncio.sleep, damit Tests nicht wirklich warten."""
    import asyncio

    async def sofort(*a, **k):
        return None
    monkeypatch.setattr(asyncio, "sleep", sofort)
