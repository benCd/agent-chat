"""MCP server exposing agent-chat tools via FastMCP (stdio transport)."""

from __future__ import annotations

import atexit
import json
import os
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from .core.models import AgentStatus, SenderType
from .core.store import MessageStore, SessionManager

mcp = FastMCP("agent-chat")

_store: MessageStore | None = None


def _get_store() -> MessageStore:
    """Lazily initialise and return the shared MessageStore."""
    global _store
    if _store is None:
        sm = SessionManager()
        session_id = sm.resolve_session(os.environ.get("AGENT_CHAT_SESSION"))
        _store = sm.get_store(session_id)
        atexit.register(_close_store)
    return _store


def _close_store():
    """Shutdown hook to close the global store cleanly."""
    global _store
    if _store is not None:
        _store.close()
        _store = None


def _default_str(obj):
    """JSON default serialiser for datetime and enums."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, AgentStatus | SenderType):
        return obj.value
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _dump(obj) -> str:
    if isinstance(obj, list):
        return json.dumps([o.model_dump() for o in obj], default=_default_str)
    return json.dumps(obj.model_dump(), default=_default_str)


# ── Tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
def register_agent(
    agent_id: str,
    display_name: str,
    model: str = "",
    current_task: str = "",
) -> str:
    """Register an agent in the chatroom."""
    store = _get_store()
    agent = store.register_agent(
        agent_id=agent_id,
        display_name=display_name,
        model=model or None,
        current_task=current_task or None,
    )
    return _dump(agent)


@mcp.tool()
def check_messages(agent_id: str, channel: str = "general") -> str:
    """Get new messages since this agent last checked."""
    store = _get_store()
    messages = store.check_messages(agent_id, channel)
    return _dump(messages)


@mcp.tool()
def post_message(
    agent_id: str,
    content: str,
    channel: str = "general",
    parent_id: str = "",
) -> str:
    """Post a markdown message to a channel."""
    store = _get_store()
    msg = store.post_message(
        sender_id=agent_id,
        content=content,
        channel=channel,
        sender_type=SenderType.AGENT,
        parent_id=parent_id or None,
    )
    return _dump(msg)


@mcp.tool()
def update_status(agent_id: str, status: str, detail: str = "") -> str:
    """Update agent status (idle/working/waiting/done)."""
    store = _get_store()
    try:
        agent_status = AgentStatus(status)
    except ValueError:
        valid = ", ".join(s.value for s in AgentStatus)
        return json.dumps({"error": f"Invalid status {status!r}. Must be one of: {valid}"})
    agent = store.update_agent_status(
        agent_id=agent_id,
        status=agent_status,
        detail=detail or None,
    )
    if agent is None:
        return json.dumps({"error": f"Agent {agent_id!r} not found"})
    return _dump(agent)


@mcp.tool()
def update_task(agent_id: str, current_task: str) -> str:
    """Update the current task description for an agent."""
    store = _get_store()
    agent = store.update_agent_task(agent_id, current_task)
    if agent is None:
        return json.dumps({"error": f"Agent {agent_id!r} not found"})
    return _dump(agent)


@mcp.tool()
def ask_question(agent_id: str, question: str, channel: str = "general") -> str:
    """Post a question that other agents or humans can answer."""
    store = _get_store()
    msg = store.post_message(
        sender_id=agent_id,
        content=question,
        channel=channel,
        sender_type=SenderType.AGENT,
        is_question=True,
    )
    return _dump(msg)


@mcp.tool()
def get_answers(question_id: str) -> str:
    """Get replies to a question."""
    store = _get_store()
    replies = store.get_replies(question_id)
    return _dump(replies)


@mcp.tool()
def list_agents() -> str:
    """List all registered agents."""
    store = _get_store()
    agents = store.list_agents()
    return _dump(agents)


@mcp.tool()
def list_channels() -> str:
    """List all channels."""
    store = _get_store()
    channels = store.list_channels()
    return _dump(channels)


# ── Entrypoint ───────────────────────────────────────────────────────────────

def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
