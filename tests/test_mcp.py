"""Tests for the MCP server tool functions.

We call the tool handler functions directly, bypassing the MCP transport layer.
Each test gets its own temporary MessageStore so tests are fully isolated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_chat.core.store import MessageStore, SessionManager
from agent_chat import mcp_server


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path: Path):
    """Inject a fresh in-memory-style store for every test."""
    sm = SessionManager(base_dir=tmp_path / "sessions")
    sid = sm.resolve_session("test-session")
    store = sm.get_store(sid)
    mcp_server._store = store
    yield store
    store.close()
    mcp_server._store = None


# ── register_agent ───────────────────────────────────────────────────────────


def test_register_agent_basic():
    result = json.loads(mcp_server.register_agent("a1", "Alice"))
    assert result["id"] == "a1"
    assert result["display_name"] == "Alice"
    assert result["status"] == "idle"


def test_register_agent_with_model_and_task():
    result = json.loads(
        mcp_server.register_agent("b1", "Bob", model="gpt-4", current_task="coding")
    )
    assert result["model"] == "gpt-4"
    assert result["current_task"] == "coding"


def test_register_agent_empty_optional_fields():
    result = json.loads(mcp_server.register_agent("c1", "Carol", model="", current_task=""))
    assert result["model"] is None
    assert result["current_task"] is None


# ── post_message / check_messages ────────────────────────────────────────────


def test_post_and_check_messages():
    mcp_server.register_agent("sender", "Sender")
    mcp_server.register_agent("reader", "Reader")

    mcp_server.post_message("sender", "Hello!")

    msgs = json.loads(mcp_server.check_messages("reader"))
    assert len(msgs) == 1
    assert msgs[0]["content"] == "Hello!"
    assert msgs[0]["sender_id"] == "sender"

    # Second check returns nothing new
    msgs2 = json.loads(mcp_server.check_messages("reader"))
    assert len(msgs2) == 0


def test_post_message_to_custom_channel():
    mcp_server.register_agent("a", "Agent")
    mcp_server.register_agent("b", "Agent2")

    result = json.loads(mcp_server.post_message("a", "hi", channel="dev"))
    assert result["channel"] == "dev"

    msgs = json.loads(mcp_server.check_messages("b", channel="dev"))
    assert len(msgs) == 1


def test_post_message_with_parent():
    mcp_server.register_agent("a", "A")
    parent = json.loads(mcp_server.post_message("a", "parent msg"))
    child = json.loads(
        mcp_server.post_message("a", "reply", parent_id=parent["id"])
    )
    assert child["parent_id"] == parent["id"]


# ── update_status ────────────────────────────────────────────────────────────


def test_update_status():
    mcp_server.register_agent("w1", "Worker")
    result = json.loads(mcp_server.update_status("w1", "working", detail="building"))
    assert result["status"] == "working"
    assert result["current_task"] == "building"


def test_update_status_unknown_agent():
    result = json.loads(mcp_server.update_status("ghost", "idle"))
    assert "error" in result


# ── update_task ──────────────────────────────────────────────────────────────


def test_update_task():
    mcp_server.register_agent("t1", "Tasker")
    result = json.loads(mcp_server.update_task("t1", "reviewing PR"))
    assert result["current_task"] == "reviewing PR"


def test_update_task_unknown_agent():
    result = json.loads(mcp_server.update_task("ghost", "noop"))
    assert "error" in result


# ── ask_question / get_answers ───────────────────────────────────────────────


def test_ask_and_get_answers():
    mcp_server.register_agent("q1", "Questioner")
    mcp_server.register_agent("a1", "Answerer")

    q = json.loads(mcp_server.ask_question("q1", "What is 2+2?"))
    assert q["is_question"] is True

    # Post a reply
    mcp_server.post_message("a1", "It's 4", parent_id=q["id"])

    answers = json.loads(mcp_server.get_answers(q["id"]))
    assert len(answers) == 1
    assert answers[0]["content"] == "It's 4"


def test_get_answers_empty():
    mcp_server.register_agent("q2", "Q")
    q = json.loads(mcp_server.ask_question("q2", "Anyone?"))
    answers = json.loads(mcp_server.get_answers(q["id"]))
    assert answers == []


# ── list_agents ──────────────────────────────────────────────────────────────


def test_list_agents_empty():
    agents = json.loads(mcp_server.list_agents())
    assert agents == []


def test_list_agents():
    mcp_server.register_agent("x1", "X")
    mcp_server.register_agent("x2", "Y")
    agents = json.loads(mcp_server.list_agents())
    assert len(agents) == 2
    ids = {a["id"] for a in agents}
    assert ids == {"x1", "x2"}


# ── list_channels ────────────────────────────────────────────────────────────


def test_list_channels_default():
    channels = json.loads(mcp_server.list_channels())
    names = [c["name"] for c in channels]
    assert "general" in names


def test_list_channels_after_post():
    mcp_server.register_agent("ch1", "CH")
    mcp_server.post_message("ch1", "hi", channel="ops")
    channels = json.loads(mcp_server.list_channels())
    names = {c["name"] for c in channels}
    assert "ops" in names
