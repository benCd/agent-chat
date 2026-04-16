"""Data models for agent-chat."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


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


MAX_CONTENT_LENGTH = 100_000
MAX_SENDER_ID_LENGTH = 256


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

    @field_validator("sender_id")
    @classmethod
    def sender_id_must_be_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("sender_id must not be empty")
        if len(v) > MAX_SENDER_ID_LENGTH:
            raise ValueError(f"sender_id exceeds {MAX_SENDER_ID_LENGTH} characters")
        return v

    @field_validator("content")
    @classmethod
    def content_must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("content must not be empty")
        if len(v) > MAX_CONTENT_LENGTH:
            raise ValueError(f"content exceeds {MAX_CONTENT_LENGTH} characters")
        return v


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
