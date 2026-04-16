"""Textual TUI application for agent-chat."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import (
    Footer,
    Header,
    Input,
    ListItem,
    ListView,
    Markdown,
    Static,
)

from ..core.models import Agent, AgentStatus, Channel, Message, SenderType
from ..core.store import MessageStore, SessionManager

# ── Colour helpers ──────────────────────────────────────────────────

_AGENT_COLOURS = [
    "cyan",
    "green",
    "magenta",
    "yellow",
    "blue",
    "red",
    "bright_cyan",
    "bright_green",
    "bright_magenta",
    "bright_yellow",
]

STATUS_BADGES: dict[AgentStatus, str] = {
    AgentStatus.WORKING: "🟢 working",
    AgentStatus.WAITING: "🟡 waiting",
    AgentStatus.IDLE: "⚪ idle",
    AgentStatus.DONE: "✅ done",
}


def _colour_for_sender(sender_id: str) -> str:
    """Deterministic colour based on sender id hash."""
    return _AGENT_COLOURS[hash(sender_id) % len(_AGENT_COLOURS)]


def _time_ago(dt: datetime) -> str:
    """Human-readable time-since string."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


# ── Channel sidebar ────────────────────────────────────────────────

class ChannelItem(ListItem):
    """A single channel entry in the sidebar."""

    def __init__(self, channel_name: str, active: bool = False) -> None:
        super().__init__()
        self.channel_name = channel_name
        self._active = active

    def compose(self) -> ComposeResult:
        prefix = "▸ " if self._active else "  "
        yield Static(f"{prefix}# {self.channel_name}", classes="channel-label")


class ChannelList(Vertical):
    """Left sidebar listing channels."""

    DEFAULT_CSS = """
    ChannelList {
        width: 24;
        min-width: 20;
        border-right: solid $surface-lighten-2;
        padding: 0 1;
    }
    ChannelList .sidebar-title {
        text-style: bold;
        color: $text;
        padding: 1 0;
        text-align: center;
    }
    ChannelList ListView {
        height: 1fr;
        background: transparent;
    }
    ChannelList .channel-label {
        padding: 0 1;
    }
    """

    def __init__(
        self,
        channels: list[str],
        active: str = "general",
    ) -> None:
        super().__init__()
        self._channels = channels
        self._active = active

    def compose(self) -> ComposeResult:
        yield Static("📡 Channels", classes="sidebar-title")
        lv = ListView(
            *[
                ChannelItem(ch, active=(ch == self._active))
                for ch in self._channels
            ],
            id="channel-list",
        )
        yield lv

    def rebuild(self, channels: list[str], active: str) -> None:
        self._channels = channels
        self._active = active
        lv = self.query_one("#channel-list", ListView)
        lv.clear()
        for ch in channels:
            lv.append(ChannelItem(ch, active=(ch == active)))


# ── Chat area ──────────────────────────────────────────────────────

class MessageWidget(Vertical):
    """Renders a single chat message."""

    DEFAULT_CSS = """
    MessageWidget {
        padding: 0 1;
        margin: 0 0 1 0;
    }
    MessageWidget .msg-header {
        text-style: bold;
    }
    MessageWidget .msg-timestamp {
        color: $text-muted;
    }
    MessageWidget .msg-image {
        color: $warning;
    }
    """

    def __init__(self, message: Message, display_name: str, colour: str) -> None:
        super().__init__()
        self._message = message
        self._display_name = display_name
        self._colour = colour

    def compose(self) -> ComposeResult:
        msg = self._message
        ts = msg.timestamp.strftime("%H:%M:%S")
        header = f"[{self._colour}]{self._display_name}[/]  [{self._colour}]•[/]  [dim]{ts}[/]"
        yield Static(header, classes="msg-header", markup=True)
        yield Markdown(msg.content)
        if msg.image_paths:
            for img in msg.image_paths:
                fname = Path(img).name
                yield Static(f"  [📎 image: {fname}]", classes="msg-image")


class ChatArea(Vertical):
    """Central message display area."""

    DEFAULT_CSS = """
    ChatArea {
        width: 1fr;
        border-right: solid $surface-lighten-2;
    }
    ChatArea #chat-channel-name {
        text-style: bold;
        padding: 1 2;
        background: $surface;
        text-align: center;
    }
    ChatArea #messages-scroll {
        height: 1fr;
    }
    ChatArea #messages-container {
        padding: 1 1;
    }
    """

    def __init__(self, channel_name: str = "general") -> None:
        super().__init__()
        self._channel_name = channel_name

    def compose(self) -> ComposeResult:
        yield Static(f"# {self._channel_name}", id="chat-channel-name")
        with ScrollableContainer(id="messages-scroll"):
            yield Vertical(id="messages-container")

    def set_channel_title(self, name: str) -> None:
        self._channel_name = name
        self.query_one("#chat-channel-name", Static).update(f"# {name}")


# ── Agent panel (right sidebar) ───────────────────────────────────

class AgentEntry(Static):
    """Compact agent row in the right panel."""

    def __init__(self, agent: Agent) -> None:
        self._agent = agent
        badge = STATUS_BADGES.get(agent.status, "⚪ unknown")
        model_str = agent.model or "—"
        seen = _time_ago(agent.last_seen)
        markup = (
            f"[bold]{agent.display_name}[/bold]  {badge}\n"
            f"  [dim]model:[/dim] {model_str}  [dim]seen:[/dim] {seen}"
        )
        super().__init__(markup, markup=True)
        self.agent_id = agent.id


class AgentPanel(Vertical):
    """Right sidebar showing agent statuses."""

    DEFAULT_CSS = """
    AgentPanel {
        width: 30;
        min-width: 24;
        padding: 0 1;
    }
    AgentPanel .sidebar-title {
        text-style: bold;
        color: $text;
        padding: 1 0;
        text-align: center;
    }
    AgentPanel #agent-scroll {
        height: 1fr;
    }
    AgentPanel .agent-entry {
        padding: 1 1;
        margin: 0 0 1 0;
        border: round $surface-lighten-2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("🤖 Agents", classes="sidebar-title")
        with ScrollableContainer(id="agent-scroll"):
            yield Vertical(id="agent-entries")


# ── Agent detail modal ─────────────────────────────────────────────

class AgentDetailScreen(ModalScreen[None]):
    """Modal showing detailed info about an agent."""

    DEFAULT_CSS = """
    AgentDetailScreen {
        align: center middle;
    }
    AgentDetailScreen #agent-detail-box {
        width: 70;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 2 3;
    }
    AgentDetailScreen #detail-close-btn {
        margin-top: 1;
        text-align: center;
        text-style: bold;
        color: $text;
    }
    AgentDetailScreen .detail-header {
        text-style: bold;
        padding-bottom: 1;
    }
    AgentDetailScreen .detail-messages-title {
        text-style: bold;
        padding: 1 0;
    }
    AgentDetailScreen #detail-messages-scroll {
        height: auto;
        max-height: 30;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close"),
    ]

    def __init__(
        self,
        agent: Agent,
        recent_messages: list[Message],
    ) -> None:
        super().__init__()
        self._agent = agent
        self._recent_messages = recent_messages

    def compose(self) -> ComposeResult:
        a = self._agent
        badge = STATUS_BADGES.get(a.status, "⚪ unknown")
        reg = a.registered_at.strftime("%Y-%m-%d %H:%M:%S") if a.registered_at else "—"
        task = a.current_task or "—"

        with Vertical(id="agent-detail-box"):
            yield Static(
                f"[bold]{a.display_name}[/bold]  ({a.id})",
                classes="detail-header",
                markup=True,
            )
            yield Static(
                f"Status: {badge}\n"
                f"Model: {a.model or '—'}\n"
                f"Task: {task}\n"
                f"Registered: {reg}\n"
                f"Last seen: {_time_ago(a.last_seen)}",
                markup=True,
            )
            yield Static("── Recent messages ──", classes="detail-messages-title")
            with ScrollableContainer(id="detail-messages-scroll"):
                if self._recent_messages:
                    for msg in self._recent_messages[-10:]:
                        ts = msg.timestamp.strftime("%H:%M:%S")
                        yield Static(
                            f"[dim]{ts}[/dim]  {msg.content[:200]}",
                            markup=True,
                        )
                else:
                    yield Static("[dim]No messages yet.[/dim]", markup=True)
            yield Static("[dim]Press Escape to close[/dim]", id="detail-close-btn", markup=True)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


# ── Main application ───────────────────────────────────────────────

class AgentChatApp(App):
    """Textual TUI for viewing an agent-chat session."""

    TITLE = "agent-chat"
    SUB_TITLE = "multi-agent collaboration"

    CSS = """
    Screen {
        background: $background;
    }
    #main-area {
        height: 1fr;
    }
    #message-input {
        dock: bottom;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+r", "force_refresh", "Refresh"),
    ]

    def __init__(
        self,
        session_id: str,
        base_dir: str | None = None,
        user_name: str = "Human",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._base_dir = base_dir
        self._session_mgr = SessionManager(base_dir)
        self._session_id = self._session_mgr.resolve_session(session_id)
        self._store: MessageStore = self._session_mgr.get_store(self._session_id)
        self._user_name = user_name
        self._current_channel = "general"
        self._displayed_msg_ids: set[str] = set()
        self._agent_name_cache: dict[str, str] = {}

    # ── helpers ─────────────────────────────────────────────────────

    def _sender_display_name(self, msg: Message) -> str:
        """Look up display name from agent registry, with cache."""
        if msg.sender_id in self._agent_name_cache:
            return self._agent_name_cache[msg.sender_id]
        agent = self._store.get_agent(msg.sender_id)
        name = agent.display_name if agent else msg.sender_id
        self._agent_name_cache[msg.sender_id] = name
        return name

    # ── compose ─────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-area"):
            channels = [c.name for c in self._store.list_channels()]
            yield ChannelList(channels, active=self._current_channel)
            yield ChatArea(self._current_channel)
            yield AgentPanel()
        yield Input(placeholder="Type a message…  (Enter to send)", id="message-input")
        yield Footer()

    # ── lifecycle ───────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._load_messages()
        self._load_agents()
        self.set_interval(1.5, self._refresh_data)

    # ── input handling ──────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        self._store.post_message(
            sender_id=self._user_name.lower().replace(" ", "-"),
            content=text,
            channel=self._current_channel,
            sender_type=SenderType.HUMAN,
        )
        # Register a pseudo-agent for the human so name lookups work
        try:
            self._store.register_agent(
                agent_id=self._user_name.lower().replace(" ", "-"),
                display_name=self._user_name,
            )
        except Exception:
            pass
        event.input.value = ""
        self._load_messages()

    # ── channel switching ───────────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ChannelItem):
            self._current_channel = item.channel_name
            self._displayed_msg_ids.clear()
            self.query_one(ChatArea).set_channel_title(self._current_channel)
            channels = [c.name for c in self._store.list_channels()]
            self.query_one(ChannelList).rebuild(channels, self._current_channel)
            self._load_messages()

    # ── agent click → detail modal ──────────────────────────────────

    def on_click(self, event) -> None:
        widget = event.widget if hasattr(event, "widget") else None
        # Walk up the widget tree to find AgentEntry
        target = widget
        while target is not None:
            if isinstance(target, AgentEntry):
                agent = self._store.get_agent(target.agent_id)
                if agent:
                    msgs = self._store.get_messages(self._current_channel)
                    agent_msgs = [m for m in msgs if m.sender_id == agent.id]
                    self.push_screen(AgentDetailScreen(agent, agent_msgs))
                return
            target = getattr(target, "parent", None)

    # ── data loading ────────────────────────────────────────────────

    def _load_messages(self) -> None:
        """Full reload of messages for the current channel."""
        container = self.query_one("#messages-container", Vertical)
        container.remove_children()
        self._displayed_msg_ids.clear()
        messages = self._store.get_messages(self._current_channel, limit=200)
        for msg in messages:
            name = self._sender_display_name(msg)
            colour = _colour_for_sender(msg.sender_id)
            container.mount(MessageWidget(msg, name, colour))
            self._displayed_msg_ids.add(msg.id)
        # Scroll to bottom
        scroll = self.query_one("#messages-scroll", ScrollableContainer)
        scroll.scroll_end(animate=False)

    def _load_agents(self) -> None:
        """Refresh the agent panel."""
        entries_container = self.query_one("#agent-entries", Vertical)
        entries_container.remove_children()
        agents = self._store.list_agents()
        for agent in agents:
            entry = AgentEntry(agent)
            entry.add_class("agent-entry")
            entries_container.mount(entry)
            self._agent_name_cache[agent.id] = agent.display_name

    def _refresh_data(self) -> None:
        """Periodic poll: append new messages, refresh agents."""
        # Check for new messages
        messages = self._store.get_messages(self._current_channel, limit=200)
        new_msgs = [m for m in messages if m.id not in self._displayed_msg_ids]
        if new_msgs:
            container = self.query_one("#messages-container", Vertical)
            for msg in new_msgs:
                name = self._sender_display_name(msg)
                colour = _colour_for_sender(msg.sender_id)
                container.mount(MessageWidget(msg, name, colour))
                self._displayed_msg_ids.add(msg.id)
            scroll = self.query_one("#messages-scroll", ScrollableContainer)
            scroll.scroll_end(animate=False)

        # Refresh channels
        channels = [c.name for c in self._store.list_channels()]
        self.query_one(ChannelList).rebuild(channels, self._current_channel)

        # Refresh agents
        self._load_agents()

    def action_force_refresh(self) -> None:
        self._refresh_data()
