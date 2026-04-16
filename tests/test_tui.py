"""Tests for the Textual TUI application."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent_chat.core.models import AgentStatus, SenderType
from agent_chat.core.store import MessageStore, SessionManager
from agent_chat.tui.app import (
    AgentChatApp,
    AgentDetailScreen,
    AgentEntry,
    AgentPanel,
    ChannelItem,
    ChannelList,
    ChatArea,
    MessageWidget,
)


@pytest.fixture
def session_env():
    """Create a temporary session with test data and return (session_id, base_dir)."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "sessions"
        mgr = SessionManager(base)
        session = mgr.create_session("tui-test")
        store = mgr.get_store(session.id)

        # Register agents
        store.register_agent("agent-alpha", "Alpha Bot", model="gpt-4o", current_task="Writing code")
        store.register_agent("agent-beta", "Beta Bot", model="claude-sonnet-4", current_task="Reviewing PR")
        store.update_agent_status("agent-alpha", AgentStatus.WORKING, detail="Writing code")
        store.update_agent_status("agent-beta", AgentStatus.WAITING, detail="Reviewing PR")

        # Create channels
        store.create_channel("debug", "Debug discussion")
        store.create_channel("planning", "Planning channel")

        # Post messages
        store.post_message("agent-alpha", "Hello from Alpha!", channel="general")
        store.post_message("agent-beta", "Hi Alpha, I'm here.", channel="general")
        store.post_message(
            "agent-alpha",
            "Check this **bold** markdown",
            channel="general",
        )
        store.post_message(
            "agent-alpha",
            "Here's an image",
            channel="general",
            image_paths=["/fake/path/screenshot.png"],
        )
        store.post_message("agent-beta", "Debug info here", channel="debug")

        # Human message
        store.register_agent("human", "Human")
        store.post_message(
            "human",
            "Hello agents!",
            channel="general",
            sender_type=SenderType.HUMAN,
        )

        store.close()
        yield session.id, str(base)


class TestAppStartup:
    """Verify the app starts and has the expected structure."""

    @pytest.mark.asyncio
    async def test_app_composes_without_error(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            # App should be running
            assert app.is_running

    @pytest.mark.asyncio
    async def test_has_channel_list(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            cl = app.query_one(ChannelList)
            assert cl is not None
            lv = cl.query_one("#channel-list")
            assert lv is not None

    @pytest.mark.asyncio
    async def test_has_chat_area(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            chat = app.query_one(ChatArea)
            assert chat is not None

    @pytest.mark.asyncio
    async def test_has_agent_panel(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one(AgentPanel)
            assert panel is not None

    @pytest.mark.asyncio
    async def test_has_input_bar(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            inp = app.query_one("#message-input")
            assert inp is not None

    @pytest.mark.asyncio
    async def test_has_header_and_footer(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            from textual.widgets import Header, Footer
            assert app.query_one(Header) is not None
            assert app.query_one(Footer) is not None


class TestMessageDisplay:
    """Verify messages are loaded and displayed."""

    @pytest.mark.asyncio
    async def test_messages_rendered(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            widgets = app.query(MessageWidget)
            # We posted 5 messages to "general" (4 from agents, 1 from human)
            assert len(widgets) == 5

    @pytest.mark.asyncio
    async def test_image_indicator_present(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            # Find the message with image_paths
            msg_widgets = app.query(MessageWidget)
            found_image = False
            for mw in msg_widgets:
                if mw._message.image_paths:
                    found_image = True
                    # There should be a Static with the image indicator
                    img_statics = mw.query(".msg-image")
                    assert len(img_statics) >= 1
            assert found_image


class TestAgentDisplay:
    """Verify agent entries in the right panel."""

    @pytest.mark.asyncio
    async def test_agents_listed(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            entries = app.query(AgentEntry)
            # 3 agents: alpha, beta, human
            assert len(entries) == 3


class TestChannelSwitching:
    """Verify channel switching works."""

    @pytest.mark.asyncio
    async def test_switch_channel(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            # Initially on general with 5 messages
            assert len(app.query(MessageWidget)) == 5

            # Switch to debug channel by simulating channel selection
            app._current_channel = "debug"
            app._displayed_msg_ids.clear()
            app.query_one(ChatArea).set_channel_title("debug")
            app._load_messages()
            await pilot.pause()

            # Debug channel has 1 message
            assert len(app.query(MessageWidget)) == 1


class TestMessageSending:
    """Verify sending messages from the input bar."""

    @pytest.mark.asyncio
    async def test_send_message(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            initial_count = len(app.query(MessageWidget))

            inp = app.query_one("#message-input")
            inp.focus()
            await pilot.pause()
            await pilot.press("H", "e", "l", "l", "o")
            await pilot.press("enter")
            await pilot.pause()

            # Should have one more message
            assert len(app.query(MessageWidget)) == initial_count + 1


class TestAgentDetailModal:
    """Verify the agent detail modal can be opened."""

    @pytest.mark.asyncio
    async def test_push_agent_detail(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            # Manually push the modal screen
            agent = app._store.get_agent("agent-alpha")
            msgs = app._store.get_messages("general")
            agent_msgs = [m for m in msgs if m.sender_id == "agent-alpha"]
            app.push_screen(AgentDetailScreen(agent, agent_msgs))
            await pilot.pause()

            # The modal should now be active
            assert isinstance(app.screen, AgentDetailScreen)

            # Dismiss with Escape
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, AgentDetailScreen)


class TestAutoRefresh:
    """Verify the auto-refresh picks up new data."""

    @pytest.mark.asyncio
    async def test_refresh_picks_up_new_messages(self, session_env):
        session_id, base_dir = session_env
        app = AgentChatApp(session_id=session_id, base_dir=base_dir)
        async with app.run_test(size=(120, 40)) as pilot:
            initial_count = len(app.query(MessageWidget))

            # Post a message directly to the store (simulating another agent)
            app._store.post_message(
                "agent-alpha",
                "Background message",
                channel="general",
            )

            # Trigger refresh
            app._refresh_data()
            await pilot.pause()

            assert len(app.query(MessageWidget)) == initial_count + 1
