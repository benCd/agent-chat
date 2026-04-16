"""Data models for agent-chat."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"
    DONE = "done"


class SenderType(str, Enum):
    AGENT = "agent"
    HUMAN = "human"


class Agent(BaseModel):
    id: str
    display_name: str
    model: Optional[str] = None
    status: AgentStatus = AgentStatus.IDLE
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    current_task: Optional[str] = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Channel(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Message(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    channel: str = "general"
    sender_id: str
    sender_type: SenderType
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Optional[dict] = None
    parent_id: Optional[str] = None
    image_paths: list[str] = Field(default_factory=list)
    is_question: bool = False


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
