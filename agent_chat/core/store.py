"""SQLite-backed message store with session management."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Agent, AgentStatus, Channel, Message, SenderType, Session

DEFAULT_BASE_DIR = Path.home() / ".agent-chat" / "sessions"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS session_meta (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    model TEXT,
    status TEXT NOT NULL DEFAULT 'idle',
    last_seen TEXT NOT NULL,
    current_task TEXT,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL DEFAULT 'general',
    sender_id TEXT NOT NULL,
    sender_type TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    metadata TEXT,
    parent_id TEXT,
    image_paths TEXT DEFAULT '[]',
    is_question INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (channel) REFERENCES channels(name),
    FOREIGN KEY (parent_id) REFERENCES messages(id)
);

CREATE TABLE IF NOT EXISTS agent_last_read (
    agent_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    last_read_ts TEXT NOT NULL,
    PRIMARY KEY (agent_id, channel)
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_ts ON messages(channel, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages(parent_id);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id);
"""


def _retry_on_busy(func):
    """Decorator to retry on SQLITE_BUSY with exponential backoff."""
    def wrapper(*args, **kwargs):
        max_retries = 5
        delay = 0.05
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                if "locked" in str(e) or "busy" in str(e):
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                        delay *= 2
                        continue
                raise
    return wrapper


class MessageStore:
    """SQLite-backed store for messages, agents, and channels."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                timeout=10,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        # Ensure #general channel exists
        try:
            conn.execute(
                "INSERT OR IGNORE INTO channels (id, name, description, created_at) "
                "VALUES (?, ?, ?, ?)",
                ("general", "general", "General discussion", datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # --- Agents ---

    @_retry_on_busy
    def register_agent(
        self,
        agent_id: str,
        display_name: str,
        model: Optional[str] = None,
        current_task: Optional[str] = None,
    ) -> Agent:
        now = datetime.now(timezone.utc)
        agent = Agent(
            id=agent_id,
            display_name=display_name,
            model=model,
            current_task=current_task,
            status=AgentStatus.IDLE,
            last_seen=now,
            registered_at=now,
        )
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO agents (id, display_name, model, status, last_seen, current_task, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (agent.id, agent.display_name, agent.model, agent.status.value,
             agent.last_seen.isoformat(), agent.current_task, agent.registered_at.isoformat()),
        )
        conn.commit()
        return agent

    @_retry_on_busy
    def get_agent(self, agent_id: str) -> Optional[Agent]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_agent(row)

    @_retry_on_busy
    def list_agents(self) -> list[Agent]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM agents ORDER BY display_name").fetchall()
        return [self._row_to_agent(r) for r in rows]

    @_retry_on_busy
    def update_agent_status(
        self,
        agent_id: str,
        status: AgentStatus,
        detail: Optional[str] = None,
    ) -> Optional[Agent]:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        if detail is not None:
            conn.execute(
                "UPDATE agents SET status = ?, current_task = ?, last_seen = ? WHERE id = ?",
                (status.value, detail, now, agent_id),
            )
        else:
            conn.execute(
                "UPDATE agents SET status = ?, last_seen = ? WHERE id = ?",
                (status.value, now, agent_id),
            )
        conn.commit()
        return self.get_agent(agent_id)

    @_retry_on_busy
    def update_agent_task(self, agent_id: str, current_task: str) -> Optional[Agent]:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE agents SET current_task = ?, last_seen = ? WHERE id = ?",
            (current_task, now, agent_id),
        )
        conn.commit()
        return self.get_agent(agent_id)

    @_retry_on_busy
    def heartbeat(self, agent_id: str):
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE agents SET last_seen = ? WHERE id = ?", (now, agent_id))
        conn.commit()

    # --- Channels ---

    @_retry_on_busy
    def create_channel(self, name: str, description: Optional[str] = None) -> Channel:
        channel = Channel(name=name, description=description)
        conn = self._get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO channels (id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (channel.id, channel.name, channel.description, channel.created_at.isoformat()),
        )
        conn.commit()
        return channel

    @_retry_on_busy
    def list_channels(self) -> list[Channel]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM channels ORDER BY name").fetchall()
        return [self._row_to_channel(r) for r in rows]

    @_retry_on_busy
    def get_channel(self, name: str) -> Optional[Channel]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM channels WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return self._row_to_channel(row)

    # --- Messages ---

    @_retry_on_busy
    def post_message(
        self,
        sender_id: str,
        content: str,
        channel: str = "general",
        sender_type: SenderType = SenderType.AGENT,
        parent_id: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
        is_question: bool = False,
        metadata: Optional[dict] = None,
    ) -> Message:
        # Auto-create channel if it doesn't exist
        if self.get_channel(channel) is None:
            self.create_channel(channel)

        msg = Message(
            sender_id=sender_id,
            sender_type=sender_type,
            content=content,
            channel=channel,
            parent_id=parent_id,
            image_paths=image_paths or [],
            is_question=is_question,
            metadata=metadata,
        )
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO messages (id, channel, sender_id, sender_type, content, timestamp, "
            "metadata, parent_id, image_paths, is_question) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg.id, msg.channel, msg.sender_id, msg.sender_type.value,
                msg.content, msg.timestamp.isoformat(),
                json.dumps(msg.metadata) if msg.metadata else None,
                msg.parent_id, json.dumps(msg.image_paths), int(msg.is_question),
            ),
        )
        # Update agent last_seen
        conn.execute(
            "UPDATE agents SET last_seen = ? WHERE id = ?",
            (msg.timestamp.isoformat(), sender_id),
        )
        conn.commit()
        return msg

    @_retry_on_busy
    def get_messages(
        self,
        channel: str = "general",
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[Message]:
        conn = self._get_conn()
        if since:
            rows = conn.execute(
                "SELECT * FROM messages WHERE channel = ? AND timestamp > ? "
                "ORDER BY timestamp ASC LIMIT ?",
                (channel, since.isoformat(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages WHERE channel = ? ORDER BY timestamp ASC LIMIT ?",
                (channel, limit),
            ).fetchall()
        return [self._row_to_message(r) for r in rows]

    @_retry_on_busy
    def get_all_messages(self, since: Optional[datetime] = None, limit: int = 200) -> list[Message]:
        conn = self._get_conn()
        if since:
            rows = conn.execute(
                "SELECT * FROM messages WHERE timestamp > ? ORDER BY timestamp ASC LIMIT ?",
                (since.isoformat(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages ORDER BY timestamp ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_message(r) for r in rows]

    @_retry_on_busy
    def check_messages(self, agent_id: str, channel: str = "general") -> list[Message]:
        """Get new messages since this agent last checked."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT last_read_ts FROM agent_last_read WHERE agent_id = ? AND channel = ?",
            (agent_id, channel),
        ).fetchone()

        if row:
            since = row["last_read_ts"]
            messages = conn.execute(
                "SELECT * FROM messages WHERE channel = ? AND timestamp > ? "
                "AND sender_id != ? ORDER BY timestamp ASC",
                (channel, since, agent_id),
            ).fetchall()
        else:
            messages = conn.execute(
                "SELECT * FROM messages WHERE channel = ? AND sender_id != ? "
                "ORDER BY timestamp ASC",
                (channel, agent_id),
            ).fetchall()

        # Update last read timestamp
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO agent_last_read (agent_id, channel, last_read_ts) "
            "VALUES (?, ?, ?)",
            (agent_id, channel, now),
        )
        # Heartbeat
        conn.execute("UPDATE agents SET last_seen = ? WHERE id = ?", (now, agent_id))
        conn.commit()

        return [self._row_to_message(r) for r in messages]

    @_retry_on_busy
    def get_replies(self, message_id: str) -> list[Message]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM messages WHERE parent_id = ? ORDER BY timestamp ASC",
            (message_id,),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    @_retry_on_busy
    def get_questions(self, channel: str = "general", unanswered_only: bool = True) -> list[Message]:
        conn = self._get_conn()
        if unanswered_only:
            rows = conn.execute(
                "SELECT m.* FROM messages m WHERE m.channel = ? AND m.is_question = 1 "
                "AND NOT EXISTS (SELECT 1 FROM messages r WHERE r.parent_id = m.id) "
                "ORDER BY m.timestamp ASC",
                (channel,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages WHERE channel = ? AND is_question = 1 "
                "ORDER BY timestamp ASC",
                (channel,),
            ).fetchall()
        return [self._row_to_message(r) for r in rows]

    # --- Row converters ---

    @staticmethod
    def _row_to_agent(row: sqlite3.Row) -> Agent:
        return Agent(
            id=row["id"],
            display_name=row["display_name"],
            model=row["model"],
            status=AgentStatus(row["status"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
            current_task=row["current_task"],
            registered_at=datetime.fromisoformat(row["registered_at"]),
        )

    @staticmethod
    def _row_to_channel(row: sqlite3.Row) -> Channel:
        return Channel(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> Message:
        return Message(
            id=row["id"],
            channel=row["channel"],
            sender_id=row["sender_id"],
            sender_type=SenderType(row["sender_type"]),
            content=row["content"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            parent_id=row["parent_id"],
            image_paths=json.loads(row["image_paths"]) if row["image_paths"] else [],
            is_question=bool(row["is_question"]),
        )


class SessionManager:
    """Manages chat sessions (chatrooms)."""

    def __init__(self, base_dir: Optional[str | Path] = None):
        self.base_dir = Path(base_dir) if base_dir else DEFAULT_BASE_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, name: str) -> Session:
        session = Session(name=name)
        session_dir = self.base_dir / session.id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "attachments").mkdir(exist_ok=True)

        # Initialize the DB and store session metadata
        store = MessageStore(session_dir / "chat.db")
        conn = store._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO session_meta (id, name, created_at) VALUES (?, ?, ?)",
            (session.id, session.name, session.created_at.isoformat()),
        )
        conn.commit()
        store.close()
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        session_dir = self.base_dir / session_id
        if not (session_dir / "chat.db").exists():
            return None
        store = MessageStore(session_dir / "chat.db")
        conn = store._get_conn()
        row = conn.execute("SELECT * FROM session_meta WHERE id = ?", (session_id,)).fetchone()
        store.close()
        if row is None:
            return None
        return Session(
            id=row["id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_sessions(self) -> list[Session]:
        sessions = []
        if not self.base_dir.exists():
            return sessions
        for entry in sorted(self.base_dir.iterdir()):
            if entry.is_dir() and (entry / "chat.db").exists():
                session = self.get_session(entry.name)
                if session:
                    sessions.append(session)
        return sessions

    def get_store(self, session_id: str) -> MessageStore:
        session_dir = self.base_dir / session_id
        return MessageStore(session_dir / "chat.db")

    def get_attachments_dir(self, session_id: str) -> Path:
        d = self.base_dir / session_id / "attachments"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def resolve_session(self, session_id_or_name: Optional[str] = None) -> str:
        """Resolve a session ID from ID, name, env var, or default."""
        # Check env var
        if session_id_or_name is None:
            session_id_or_name = os.environ.get("AGENT_CHAT_SESSION")

        if session_id_or_name is None:
            # Use or create default session
            default_sessions = [s for s in self.list_sessions() if s.name == "default"]
            if default_sessions:
                return default_sessions[0].id
            session = self.create_session("default")
            return session.id

        # Try as session ID first
        if self.get_session(session_id_or_name):
            return session_id_or_name

        # Try as session name
        for s in self.list_sessions():
            if s.name == session_id_or_name:
                return s.id

        # Create new session with this name
        session = self.create_session(session_id_or_name)
        return session.id
