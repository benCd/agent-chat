"""Shared test fixtures for agent-chat."""

import tempfile
from pathlib import Path

import pytest

from agent_chat.core.store import MessageStore, SessionManager


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def store(tmp_dir):
    s = MessageStore(tmp_dir / "test.db")
    yield s
    s.close()


@pytest.fixture
def session_mgr(tmp_dir):
    return SessionManager(tmp_dir / "sessions")


@pytest.fixture
def session_env(tmp_dir, monkeypatch):
    """Create a session and set AGENT_CHAT_SESSION env var."""
    mgr = SessionManager(tmp_dir / "sessions")
    session = mgr.create_session("test-session")
    monkeypatch.setenv("AGENT_CHAT_SESSION", session.id)
    return tmp_dir / "sessions", session
