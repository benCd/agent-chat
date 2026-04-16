"""CLI for agent-chat."""

from __future__ import annotations

import json as json_module
from pathlib import Path
from typing import Optional

import typer

from agent_chat.core.models import AgentStatus, SenderType
from agent_chat.core.store import SessionManager

app = typer.Typer(help="Agent Chat — communication protocol for LLM agents")
session_app = typer.Typer(help="Create sessions")
sessions_app = typer.Typer(help="List and manage sessions")
app.add_typer(session_app, name="session")
app.add_typer(sessions_app, name="sessions")

# Override for testing
_base_dir_override: Optional[Path] = None


def _mgr() -> SessionManager:
    if _base_dir_override is not None:
        return SessionManager(base_dir=_base_dir_override)
    return SessionManager()


def _resolve(session: Optional[str] = None):
    mgr = _mgr()
    sid = mgr.resolve_session(session)
    store = mgr.get_store(sid)
    return sid, store


# ── Session commands ─────────────────────────────────────────────────────────

@session_app.command("create")
def session_create(
    name: str = typer.Argument(..., help="Session name"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Create a new chatroom session."""
    session = _mgr().create_session(name)
    if json_output:
        typer.echo(json_module.dumps({
            "id": session.id, "name": session.name,
            "created_at": session.created_at.isoformat(),
        }))
    else:
        typer.echo(session.id)


@sessions_app.command("list")
def sessions_list(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """List all sessions."""
    sessions = _mgr().list_sessions()
    if json_output:
        typer.echo(json_module.dumps([
            {"id": s.id, "name": s.name, "created_at": s.created_at.isoformat()}
            for s in sessions
        ]))
    else:
        if not sessions:
            typer.echo("No sessions found.")
        else:
            for s in sessions:
                typer.echo(
                    f"{s.name}  {s.id}  {s.created_at.strftime('%Y-%m-%d %H:%M')}"
                )


@sessions_app.command("open")
def sessions_open(
    session_id: str = typer.Argument(..., help="Session ID"),
):
    """Open a session TUI (placeholder)."""
    typer.echo(f"TUI not yet implemented. Session: {session_id}")


# ── Agent commands ───────────────────────────────────────────────────────────

@app.command()
def register(
    agent_id: str = typer.Argument(..., help="Unique agent identifier"),
    name: str = typer.Option(..., "--name", help="Display name"),
    model: Optional[str] = typer.Option(None, "--model", help="Model name"),
    task: Optional[str] = typer.Option(None, "--task", help="Current task"),
    session: Optional[str] = typer.Option(None, "--session", help="Session ID or name"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Register an agent in the session."""
    _, store = _resolve(session)
    agent = store.register_agent(agent_id, name, model=model, current_task=task)
    store.close()
    if json_output:
        typer.echo(json_module.dumps({
            "id": agent.id, "name": agent.display_name,
            "model": agent.model, "status": agent.status.value,
            "task": agent.current_task,
        }))
    else:
        typer.echo(f"Registered {agent.display_name} ({agent.id})")


@app.command()
def check(
    agent_id: str = typer.Argument(..., help="Agent ID"),
    channel: str = typer.Option("general", "--channel", help="Channel"),
    session: Optional[str] = typer.Option(None, "--session", help="Session ID or name"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Check for new messages since last check."""
    _, store = _resolve(session)
    messages = store.check_messages(agent_id, channel)
    store.close()
    if json_output:
        typer.echo(json_module.dumps([
            {"id": m.id, "sender": m.sender_id, "content": m.content,
             "channel": m.channel, "timestamp": m.timestamp.isoformat()}
            for m in messages
        ]))
    else:
        if not messages:
            typer.echo("No new messages.")
        else:
            for m in messages:
                typer.echo(f"[{m.sender_id}] {m.content}")


@app.command()
def post(
    agent_id: str = typer.Argument(..., help="Agent ID"),
    message: str = typer.Argument(..., help="Message content"),
    channel: str = typer.Option("general", "--channel", help="Channel"),
    session: Optional[str] = typer.Option(None, "--session", help="Session ID or name"),
    image: Optional[Path] = typer.Option(None, "--image", help="Image attachment path"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Post a message to a channel."""
    _, store = _resolve(session)
    image_paths = [str(image)] if image else None
    msg = store.post_message(
        sender_id=agent_id, content=message, channel=channel,
        sender_type=SenderType.AGENT, image_paths=image_paths,
    )
    store.close()
    if json_output:
        typer.echo(json_module.dumps({
            "id": msg.id, "content": msg.content,
            "channel": msg.channel, "timestamp": msg.timestamp.isoformat(),
        }))
    else:
        typer.echo(f"Posted: {msg.id}")


@app.command()
def status(
    agent_id: str = typer.Argument(..., help="Agent ID"),
    status_value: str = typer.Argument(..., metavar="STATUS",
                                       help="idle | working | waiting | done"),
    detail: Optional[str] = typer.Option(None, "--detail", help="Status detail"),
    session: Optional[str] = typer.Option(None, "--session", help="Session ID or name"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Update agent status."""
    _, store = _resolve(session)
    try:
        agent_status = AgentStatus(status_value)
    except ValueError:
        typer.echo(
            f"Invalid status: {status_value}. "
            "Must be one of: idle, working, waiting, done",
            err=True,
        )
        store.close()
        raise typer.Exit(1)
    agent = store.update_agent_status(agent_id, agent_status, detail=detail)
    store.close()
    if agent is None:
        typer.echo(f"Agent not found: {agent_id}", err=True)
        raise typer.Exit(1)
    if json_output:
        typer.echo(json_module.dumps({
            "id": agent.id, "status": agent.status.value,
            "task": agent.current_task,
        }))
    else:
        typer.echo(f"{agent.id}: {agent.status.value}")


@app.command()
def task(
    agent_id: str = typer.Argument(..., help="Agent ID"),
    description: str = typer.Argument(..., help="Task description"),
    session: Optional[str] = typer.Option(None, "--session", help="Session ID or name"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Update agent's current task."""
    _, store = _resolve(session)
    agent = store.update_agent_task(agent_id, description)
    store.close()
    if agent is None:
        typer.echo(f"Agent not found: {agent_id}", err=True)
        raise typer.Exit(1)
    if json_output:
        typer.echo(json_module.dumps({"id": agent.id, "task": agent.current_task}))
    else:
        typer.echo(f"{agent.id}: {agent.current_task}")


@app.command()
def ask(
    agent_id: str = typer.Argument(..., help="Agent ID"),
    question: str = typer.Argument(..., help="Question text"),
    channel: str = typer.Option("general", "--channel", help="Channel"),
    session: Optional[str] = typer.Option(None, "--session", help="Session ID or name"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Post a question to a channel."""
    _, store = _resolve(session)
    msg = store.post_message(
        sender_id=agent_id, content=question, channel=channel,
        sender_type=SenderType.AGENT, is_question=True,
    )
    store.close()
    if json_output:
        typer.echo(json_module.dumps({
            "id": msg.id, "content": msg.content, "channel": msg.channel,
        }))
    else:
        typer.echo(f"Question posted: {msg.id}")


@app.command()
def answers(
    question_id: str = typer.Argument(..., help="Question message ID"),
    session: Optional[str] = typer.Option(None, "--session", help="Session ID or name"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Get replies to a question."""
    _, store = _resolve(session)
    replies = store.get_replies(question_id)
    store.close()
    if json_output:
        typer.echo(json_module.dumps([
            {"id": r.id, "sender": r.sender_id, "content": r.content,
             "timestamp": r.timestamp.isoformat()}
            for r in replies
        ]))
    else:
        if not replies:
            typer.echo("No answers yet.")
        else:
            for r in replies:
                typer.echo(f"[{r.sender_id}] {r.content}")


@app.command()
def agents(
    session: Optional[str] = typer.Option(None, "--session", help="Session ID or name"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """List all agents in the session."""
    _, store = _resolve(session)
    agent_list = store.list_agents()
    store.close()
    if json_output:
        typer.echo(json_module.dumps([
            {"id": a.id, "name": a.display_name, "status": a.status.value,
             "model": a.model, "task": a.current_task}
            for a in agent_list
        ]))
    else:
        if not agent_list:
            typer.echo("No agents registered.")
        else:
            for a in agent_list:
                parts = [a.id, a.status.value]
                if a.model:
                    parts.append(a.model)
                if a.current_task:
                    parts.append(a.current_task)
                typer.echo("  ".join(parts))


@app.command("serve-mcp")
def serve_mcp(
    session: Optional[str] = typer.Option(None, "--session", help="Session ID or name"),
):
    """Start MCP server (placeholder)."""
    typer.echo("MCP server not yet implemented.")


if __name__ == "__main__":
    app()
