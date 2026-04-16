"""FastAPI web server for agent-chat.

Provides a REST API and SSE stream backed by the MessageStore,
plus serves a static HTML/JS/CSS frontend.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..core.models import AgentStatus, SenderType
from ..core.store import MessageStore, SessionManager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


# ── Request/Response schemas ────────────────────────────────────────────────

class PostMessageRequest(BaseModel):
    sender_id: str
    content: str
    channel: str = "general"
    sender_type: str = "human"
    parent_id: Optional[str] = None
    is_question: bool = False


class RegisterAgentRequest(BaseModel):
    id: str
    display_name: str
    model: Optional[str] = None


class UpdateStatusRequest(BaseModel):
    status: str
    detail: Optional[str] = None


class UpdateTaskRequest(BaseModel):
    current_task: str


class AskQuestionRequest(BaseModel):
    sender_id: str
    question: str
    channel: str = "general"


class AnswerQuestionRequest(BaseModel):
    sender_id: str
    answer: str


# ── App factory ─────────────────────────────────────────────────────────────

def create_app(session_id: str, session_mgr: Optional[SessionManager] = None) -> FastAPI:
    """Create a FastAPI app wired to a specific chat session."""
    mgr = session_mgr or SessionManager()
    store = mgr.get_store(session_id)
    session = mgr.get_session(session_id)
    session_name = session.name if session else session_id

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        store.close()

    app = FastAPI(title=f"agent-chat · {session_name}", lifespan=lifespan)

    # Serve static frontend files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── HTML entrypoint ─────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index():
        index_html = STATIC_DIR / "index.html"
        return index_html.read_text()

    # ── Session info ────────────────────────────────────────────────────

    @app.get("/api/session")
    async def get_session():
        return {"id": session_id, "name": session_name}

    # ── Agents ──────────────────────────────────────────────────────────

    @app.get("/api/agents")
    async def list_agents():
        agents = store.list_agents()
        return [_agent_dict(a) for a in agents]

    @app.post("/api/agents")
    async def register_agent(req: RegisterAgentRequest):
        agent = store.register_agent(req.id, req.display_name, model=req.model)
        return _agent_dict(agent)

    @app.put("/api/agents/{agent_id}/status")
    async def update_status(agent_id: str, req: UpdateStatusRequest):
        try:
            status = AgentStatus(req.status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {req.status}")
        agent = store.update_agent_status(agent_id, status, detail=req.detail)
        if agent is None:
            raise HTTPException(404, f"Agent not found: {agent_id}")
        return _agent_dict(agent)

    @app.put("/api/agents/{agent_id}/task")
    async def update_task(agent_id: str, req: UpdateTaskRequest):
        agent = store.update_agent_task(agent_id, req.current_task)
        if agent is None:
            raise HTTPException(404, f"Agent not found: {agent_id}")
        return _agent_dict(agent)

    # ── Channels ────────────────────────────────────────────────────────

    @app.get("/api/channels")
    async def list_channels():
        channels = store.list_channels()
        return [_channel_dict(c) for c in channels]

    # ── Messages ────────────────────────────────────────────────────────

    @app.get("/api/messages")
    async def get_messages(
        channel: str = "general",
        since: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
    ):
        since_dt = datetime.fromisoformat(since) if since else None
        messages = store.get_messages(channel=channel, since=since_dt, limit=limit)
        return [_message_dict(m) for m in messages]

    @app.get("/api/messages/all")
    async def get_all_messages(
        since: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
    ):
        since_dt = datetime.fromisoformat(since) if since else None
        messages = store.get_all_messages(since=since_dt, limit=limit)
        return [_message_dict(m) for m in messages]

    @app.post("/api/messages")
    async def post_message(req: PostMessageRequest):
        try:
            sender_type = SenderType(req.sender_type)
        except ValueError:
            raise HTTPException(400, f"Invalid sender_type: {req.sender_type}")
        msg = store.post_message(
            sender_id=req.sender_id,
            content=req.content,
            channel=req.channel,
            sender_type=sender_type,
            parent_id=req.parent_id,
            is_question=req.is_question,
        )
        return _message_dict(msg)

    # ── Questions ───────────────────────────────────────────────────────

    @app.get("/api/questions")
    async def get_questions(
        channel: str = "general",
        unanswered_only: bool = True,
    ):
        questions = store.get_questions(channel=channel, unanswered_only=unanswered_only)
        return [_message_dict(q) for q in questions]

    @app.post("/api/questions")
    async def ask_question(req: AskQuestionRequest):
        msg = store.post_message(
            sender_id=req.sender_id,
            content=req.question,
            channel=req.channel,
            sender_type=SenderType.HUMAN,
            is_question=True,
        )
        return _message_dict(msg)

    @app.get("/api/questions/{question_id}/answers")
    async def get_answers(question_id: str):
        replies = store.get_replies(question_id)
        return [_message_dict(r) for r in replies]

    @app.post("/api/questions/{question_id}/answers")
    async def answer_question(question_id: str, req: AnswerQuestionRequest):
        msg = store.post_message(
            sender_id=req.sender_id,
            content=req.answer,
            channel="general",
            sender_type=SenderType.HUMAN,
            parent_id=question_id,
        )
        return _message_dict(msg)

    # ── SSE stream ──────────────────────────────────────────────────────

    @app.get("/api/events")
    async def sse_stream(request: Request):
        """Server-Sent Events stream for real-time updates.

        Polls the store every second and emits new messages / agent changes.
        """
        async def event_generator():
            last_msg_ts: Optional[str] = None
            last_agents_hash: Optional[str] = None

            # Send initial state
            agents = store.list_agents()
            agents_data = [_agent_dict(a) for a in agents]
            agents_hash = json.dumps(agents_data, sort_keys=True)
            last_agents_hash = agents_hash
            yield _sse_event("agents", agents_data)

            while True:
                if await request.is_disconnected():
                    break

                try:
                    # Check for new messages
                    since_dt = datetime.fromisoformat(last_msg_ts) if last_msg_ts else None
                    messages = store.get_all_messages(since=since_dt, limit=50)
                    if messages:
                        last_msg_ts = messages[-1].timestamp.isoformat()
                        for msg in messages:
                            yield _sse_event("message", _message_dict(msg))

                    # Check for agent changes
                    agents = store.list_agents()
                    agents_data = [_agent_dict(a) for a in agents]
                    agents_hash = json.dumps(agents_data, sort_keys=True)
                    if agents_hash != last_agents_hash:
                        last_agents_hash = agents_hash
                        yield _sse_event("agents", agents_data)

                except Exception:
                    logger.exception("SSE poll error")

                await asyncio.sleep(1)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


# ── Helpers ─────────────────────────────────────────────────────────────────

def _agent_dict(agent) -> dict:
    return {
        "id": agent.id,
        "display_name": agent.display_name,
        "model": agent.model,
        "status": agent.status.value,
        "last_seen": agent.last_seen.isoformat(),
        "current_task": agent.current_task,
        "registered_at": agent.registered_at.isoformat(),
    }


def _channel_dict(channel) -> dict:
    return {
        "id": channel.id,
        "name": channel.name,
        "description": channel.description,
        "created_at": channel.created_at.isoformat(),
    }


def _message_dict(msg) -> dict:
    return {
        "id": msg.id,
        "channel": msg.channel,
        "sender_id": msg.sender_id,
        "sender_type": msg.sender_type.value,
        "content": msg.content,
        "timestamp": msg.timestamp.isoformat(),
        "metadata": msg.metadata,
        "parent_id": msg.parent_id,
        "image_paths": msg.image_paths,
        "is_question": msg.is_question,
    }


def _sse_event(event_type: str, data) -> str:
    payload = json.dumps(data)
    return f"event: {event_type}\ndata: {payload}\n\n"
