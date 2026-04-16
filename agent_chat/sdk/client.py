"""High-level SDK for agents to interact with the chat."""

from __future__ import annotations

import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ..core.models import Agent, AgentStatus, Message, SenderType
from ..core.store import MessageStore, SessionManager


class AgentClient:
    """High-level client for agents to participate in a chatroom.

    Usage (controlled loop):
        client = AgentClient(
            agent_id="reviewer-1",
            display_name="Code Reviewer",
            model="claude-sonnet-4",
            session="my-session",
        )
        client.update_task("Reviewing PR #42")
        client.update_status(AgentStatus.WORKING)

        while working:
            messages = client.check_messages()
            for msg in messages:
                # respond to messages
                client.post_message(f"Got it: {msg.content}")
            # ... do work ...

        client.update_status(AgentStatus.DONE)
    """

    def __init__(
        self,
        agent_id: str,
        display_name: str,
        model: Optional[str] = None,
        current_task: Optional[str] = None,
        session: Optional[str] = None,
        base_dir: Optional[str | Path] = None,
    ):
        self._session_mgr = SessionManager(base_dir)
        self._session_id = self._session_mgr.resolve_session(session)
        self._store = self._session_mgr.get_store(self._session_id)
        self._agent_id = agent_id
        self._agent = self._store.register_agent(
            agent_id=agent_id,
            display_name=display_name,
            model=model,
            current_task=current_task,
        )
        self._poll_thread: Optional[threading.Thread] = None
        self._poll_stop = threading.Event()

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def store(self) -> MessageStore:
        return self._store

    def check_messages(self, channel: str = "general") -> list[Message]:
        """Get new messages since last check (excludes own messages)."""
        return self._store.check_messages(self._agent_id, channel)

    def post_message(
        self,
        content: str,
        channel: str = "general",
        parent_id: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> Message:
        """Post a markdown message to a channel."""
        # Copy images to session attachments directory
        stored_paths = []
        if image_paths:
            att_dir = self._session_mgr.get_attachments_dir(self._session_id)
            for img_path in image_paths:
                src = Path(img_path)
                if src.exists():
                    dest = att_dir / f"{Message().id[:8]}_{src.name}"
                    shutil.copy2(src, dest)
                    stored_paths.append(str(dest))
                else:
                    stored_paths.append(img_path)

        return self._store.post_message(
            sender_id=self._agent_id,
            content=content,
            channel=channel,
            sender_type=SenderType.AGENT,
            parent_id=parent_id,
            image_paths=stored_paths or None,
        )

    def update_status(self, status: AgentStatus, detail: Optional[str] = None) -> Optional[Agent]:
        return self._store.update_agent_status(self._agent_id, status, detail)

    def update_task(self, current_task: str) -> Optional[Agent]:
        return self._store.update_agent_task(self._agent_id, current_task)

    def ask_question(
        self,
        question: str,
        channel: str = "general",
    ) -> Message:
        """Post a question that other agents or humans can answer."""
        return self._store.post_message(
            sender_id=self._agent_id,
            content=question,
            channel=channel,
            sender_type=SenderType.AGENT,
            is_question=True,
        )

    def get_answers(self, question_id: str) -> list[Message]:
        """Get replies to a question."""
        return self._store.get_replies(question_id)

    def list_agents(self) -> list[Agent]:
        return self._store.list_agents()

    def heartbeat(self):
        self._store.heartbeat(self._agent_id)

    # --- Polling ---

    def start_polling(
        self,
        callback: Callable[[list[Message]], None],
        channel: str = "general",
        interval: float = 5.0,
    ):
        """Start a background thread that polls for new messages."""
        if self._poll_thread and self._poll_thread.is_alive():
            return

        self._poll_stop.clear()

        def _poll():
            while not self._poll_stop.is_set():
                try:
                    messages = self.check_messages(channel)
                    if messages:
                        callback(messages)
                except Exception:
                    pass
                self._poll_stop.wait(interval)

        self._poll_thread = threading.Thread(target=_poll, daemon=True)
        self._poll_thread.start()

    def stop_polling(self):
        self._poll_stop.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=10)
            self._poll_thread = None

    def close(self):
        self.stop_polling()
        self._store.close()
