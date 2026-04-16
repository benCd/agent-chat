"""Tests for the core store and SDK client."""

import tempfile
import threading
import time
from pathlib import Path

import pytest

from agent_chat.core.models import AgentStatus, Message, SenderType
from agent_chat.core.store import MessageStore, SessionManager
from agent_chat.sdk.client import AgentClient


class TestMessageStore:
    def test_register_agent(self, store):
        agent = store.register_agent("a1", "Agent One", model="claude-sonnet-4", current_task="Testing")
        assert agent.id == "a1"
        assert agent.display_name == "Agent One"
        assert agent.model == "claude-sonnet-4"
        assert agent.status == AgentStatus.IDLE

    def test_list_agents(self, store):
        store.register_agent("a1", "Alpha")
        store.register_agent("a2", "Beta")
        agents = store.list_agents()
        assert len(agents) == 2
        assert agents[0].display_name == "Alpha"

    def test_update_agent_status(self, store):
        store.register_agent("a1", "Agent")
        agent = store.update_agent_status("a1", AgentStatus.WORKING, detail="Processing")
        assert agent.status == AgentStatus.WORKING
        assert agent.current_task == "Processing"

    def test_update_agent_task(self, store):
        store.register_agent("a1", "Agent")
        agent = store.update_agent_task("a1", "New task description")
        assert agent.current_task == "New task description"

    def test_post_and_get_messages(self, store):
        store.register_agent("a1", "Agent")
        msg = store.post_message("a1", "Hello world", channel="general")
        assert msg.content == "Hello world"
        assert msg.sender_type == SenderType.AGENT

        messages = store.get_messages("general")
        assert len(messages) == 1
        assert messages[0].id == msg.id

    def test_auto_create_channel(self, store):
        store.register_agent("a1", "Agent")
        store.post_message("a1", "hello", channel="new-channel")
        channels = store.list_channels()
        names = [c.name for c in channels]
        assert "new-channel" in names

    def test_check_messages_excludes_own(self, store):
        store.register_agent("a1", "Agent 1")
        store.register_agent("a2", "Agent 2")

        store.post_message("a1", "From A1")
        store.post_message("a2", "From A2")

        msgs = store.check_messages("a1")
        assert len(msgs) == 1
        assert msgs[0].sender_id == "a2"

    def test_check_messages_tracks_last_read(self, store):
        store.register_agent("a1", "Agent 1")
        store.register_agent("a2", "Agent 2")

        store.post_message("a2", "First")
        store.check_messages("a1")  # reads "First"

        store.post_message("a2", "Second")
        msgs = store.check_messages("a1")  # should only get "Second"
        assert len(msgs) == 1
        assert msgs[0].content == "Second"

    def test_questions_and_replies(self, store):
        store.register_agent("a1", "Agent")
        store.register_agent("h1", "Human")

        q = store.post_message("a1", "What's the answer?", is_question=True)
        questions = store.get_questions("general")
        assert len(questions) == 1

        store.post_message("h1", "42", parent_id=q.id, sender_type=SenderType.HUMAN)
        replies = store.get_replies(q.id)
        assert len(replies) == 1
        assert replies[0].content == "42"

        # Answered questions should not show as unanswered
        unanswered = store.get_questions("general", unanswered_only=True)
        assert len(unanswered) == 0

    def test_image_paths(self, store):
        store.register_agent("a1", "Agent")
        msg = store.post_message("a1", "Check this image", image_paths=["/tmp/img.png"])
        assert msg.image_paths == ["/tmp/img.png"]

        msgs = store.get_messages("general")
        assert msgs[0].image_paths == ["/tmp/img.png"]

    def test_channels(self, store):
        # General is auto-created
        channels = store.list_channels()
        assert any(c.name == "general" for c in channels)

        store.create_channel("debug", "Debug channel")
        ch = store.get_channel("debug")
        assert ch is not None
        assert ch.description == "Debug channel"

    def test_get_all_messages(self, store):
        store.register_agent("a1", "Agent")
        store.post_message("a1", "msg1", channel="general")
        store.post_message("a1", "msg2", channel="debug")
        msgs = store.get_all_messages()
        assert len(msgs) == 2


class TestSessionManager:
    def test_create_and_list_sessions(self, session_mgr):
        s = session_mgr.create_session("Test Session")
        assert s.name == "Test Session"
        assert (session_mgr.base_dir / s.id / "chat.db").exists()
        assert (session_mgr.base_dir / s.id / "attachments").is_dir()

        sessions = session_mgr.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].name == "Test Session"

    def test_resolve_session_by_name(self, session_mgr):
        s = session_mgr.create_session("my-chat")
        resolved = session_mgr.resolve_session("my-chat")
        assert resolved == s.id

    def test_resolve_session_default(self, session_mgr):
        sid = session_mgr.resolve_session(None)
        session = session_mgr.get_session(sid)
        assert session.name == "default"

    def test_resolve_creates_new(self, session_mgr):
        sid = session_mgr.resolve_session("brand-new")
        session = session_mgr.get_session(sid)
        assert session.name == "brand-new"

    def test_get_store(self, session_mgr):
        s = session_mgr.create_session("test")
        store = session_mgr.get_store(s.id)
        assert store is not None
        store.close()


class TestAgentClient:
    def test_basic_workflow(self, tmp_dir):
        mgr = SessionManager(tmp_dir / "sessions")
        session = mgr.create_session("test")

        client = AgentClient(
            agent_id="bot-1",
            display_name="Test Bot",
            model="test-model",
            current_task="Running tests",
            session=session.id,
            base_dir=tmp_dir / "sessions",
        )

        # Agent is registered
        agents = client.list_agents()
        assert len(agents) == 1
        assert agents[0].display_name == "Test Bot"
        assert agents[0].model == "test-model"

        # Post a message
        msg = client.post_message("Hello from bot!")
        assert msg.content == "Hello from bot!"

        # Update status
        agent = client.update_status(AgentStatus.WORKING)
        assert agent.status == AgentStatus.WORKING

        # Update task
        agent = client.update_task("New task")
        assert agent.current_task == "New task"

        client.close()

    def test_two_clients_communicate(self, tmp_dir):
        mgr = SessionManager(tmp_dir / "sessions")
        session = mgr.create_session("collab")

        c1 = AgentClient("a1", "Agent One", session=session.id, base_dir=tmp_dir / "sessions")
        c2 = AgentClient("a2", "Agent Two", session=session.id, base_dir=tmp_dir / "sessions")

        c1.post_message("Hello from Agent One")
        msgs = c2.check_messages()
        assert len(msgs) == 1
        assert msgs[0].content == "Hello from Agent One"

        c2.post_message("Hello back from Agent Two")
        msgs = c1.check_messages()
        assert len(msgs) == 1
        assert msgs[0].content == "Hello back from Agent Two"

        c1.close()
        c2.close()

    def test_ask_and_answer(self, tmp_dir):
        mgr = SessionManager(tmp_dir / "sessions")
        session = mgr.create_session("qa")

        agent = AgentClient("a1", "Questioner", session=session.id, base_dir=tmp_dir / "sessions")
        helper = AgentClient("h1", "Helper", session=session.id, base_dir=tmp_dir / "sessions")

        q = agent.ask_question("What port should I use?")
        assert q.is_question

        # Helper checks and sees the question
        msgs = helper.check_messages()
        assert len(msgs) == 1
        assert msgs[0].is_question

        # Helper answers
        helper.post_message("Use port 8080", parent_id=q.id)

        # Agent checks answers
        answers = agent.get_answers(q.id)
        assert len(answers) == 1
        assert answers[0].content == "Use port 8080"

        agent.close()
        helper.close()

    def test_polling(self, tmp_dir):
        mgr = SessionManager(tmp_dir / "sessions")
        session = mgr.create_session("poll-test")

        received = []
        c1 = AgentClient("a1", "Poller", session=session.id, base_dir=tmp_dir / "sessions")
        c2 = AgentClient("a2", "Sender", session=session.id, base_dir=tmp_dir / "sessions")

        # Let the first empty poll run before we post
        c1.start_polling(callback=lambda msgs: received.extend(msgs), interval=0.3)
        time.sleep(0.5)  # Wait for initial empty poll to set last_read_ts

        c2.post_message("Async message")
        time.sleep(1.5)  # Wait for subsequent poll to pick it up

        c1.stop_polling()
        assert len(received) >= 1
        assert received[0].content == "Async message"

        c1.close()
        c2.close()

    def test_concurrent_writes(self, tmp_dir):
        """Test that multiple agents can write concurrently without errors."""
        mgr = SessionManager(tmp_dir / "sessions")
        session = mgr.create_session("concurrent")

        clients = [
            AgentClient(f"a{i}", f"Agent {i}", session=session.id, base_dir=tmp_dir / "sessions")
            for i in range(5)
        ]
        errors = []

        def writer(client, n):
            try:
                for j in range(10):
                    client.post_message(f"Message {j} from {client.agent_id}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(c, i)) for i, c in enumerate(clients)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

        # All messages should be in the store
        msgs = clients[0].store.get_all_messages()
        assert len(msgs) == 50  # 5 agents * 10 messages

        for c in clients:
            c.close()


# ── Additional test coverage (Phase 5) ──────────────────────────────────────


class TestRetryOnBusy:
    """T2 — Test _retry_on_busy decorator."""

    def test_retries_on_locked(self, store):
        """Simulate a locked-database error that resolves on retry."""
        import sqlite3
        from agent_chat.core.store import _retry_on_busy

        call_count = 0

        @_retry_on_busy
        def flaky_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise sqlite3.OperationalError("database is locked")
            return "success"

        result = flaky_operation()
        assert result == "success"
        assert call_count == 3

    def test_non_busy_error_propagates(self):
        """Non-busy OperationalErrors should propagate immediately."""
        import sqlite3
        from agent_chat.core.store import _retry_on_busy

        @_retry_on_busy
        def always_fail():
            raise sqlite3.OperationalError("no such table: bogus")

        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            always_fail()

    def test_preserves_function_name(self):
        """functools.wraps should be applied."""
        from agent_chat.core.store import _retry_on_busy

        @_retry_on_busy
        def my_function():
            """My docstring."""
            pass

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."


class TestResolveSessionEnv:
    """T3 — Test resolve_session with env var."""

    def test_resolve_from_env_var(self, session_mgr, monkeypatch):
        s = session_mgr.create_session("env-test")
        monkeypatch.setenv("AGENT_CHAT_SESSION", s.id)
        resolved = session_mgr.resolve_session(None)
        assert resolved == s.id

    def test_explicit_overrides_env(self, session_mgr, monkeypatch):
        s1 = session_mgr.create_session("s1")
        s2 = session_mgr.create_session("s2")
        monkeypatch.setenv("AGENT_CHAT_SESSION", s1.id)
        resolved = session_mgr.resolve_session(s2.id)
        assert resolved == s2.id


class TestGetMessagesSince:
    """T4 — Test get_messages with since parameter."""

    def test_since_filter(self, store):
        store.register_agent("a1", "Agent")
        m1 = store.post_message("a1", "first")
        time.sleep(0.01)
        m2 = store.post_message("a1", "second")

        msgs = store.get_messages("general", since=m1.timestamp)
        assert len(msgs) == 1
        assert msgs[0].content == "second"


class TestMessageMetadata:
    """T5 — Test post_message with metadata round-trip."""

    def test_metadata_round_trip(self, store):
        store.register_agent("a1", "Agent")
        meta = {"pr": 42, "file": "main.py", "tags": ["review", "urgent"]}
        msg = store.post_message("a1", "review this", metadata=meta)
        assert msg.metadata == meta

        fetched = store.get_messages("general")
        assert fetched[0].metadata == meta

    def test_null_metadata(self, store):
        store.register_agent("a1", "Agent")
        msg = store.post_message("a1", "no meta")
        assert msg.metadata is None
        fetched = store.get_messages("general")
        assert fetched[0].metadata is None


class TestHeartbeat:
    """T7 — Test heartbeat() method."""

    def test_heartbeat_updates_last_seen(self, store):
        store.register_agent("a1", "Agent")
        agent_before = store.get_agent("a1")
        time.sleep(0.01)
        store.heartbeat("a1")
        agent_after = store.get_agent("a1")
        assert agent_after.last_seen > agent_before.last_seen


class TestGetQuestionsAll:
    """T8 — Test get_questions(unanswered_only=False)."""

    def test_includes_answered(self, store):
        store.register_agent("a1", "Agent")
        store.register_agent("h1", "Human")
        q = store.post_message("a1", "Question?", is_question=True)
        store.post_message("h1", "Answer!", parent_id=q.id, sender_type=SenderType.HUMAN)

        unanswered = store.get_questions("general", unanswered_only=True)
        assert len(unanswered) == 0

        all_q = store.get_questions("general", unanswered_only=False)
        assert len(all_q) == 1


class TestGetAgent:
    """T9 — Test get_agent() directly."""

    def test_get_existing_agent(self, store):
        store.register_agent("a1", "Agent One", model="gpt-4")
        agent = store.get_agent("a1")
        assert agent is not None
        assert agent.display_name == "Agent One"
        assert agent.model == "gpt-4"

    def test_get_nonexistent_agent(self, store):
        agent = store.get_agent("missing")
        assert agent is None


class TestDuplicateRegistration:
    """T11 — Test duplicate agent registration preserves data."""

    def test_preserves_registered_at(self, store):
        a1 = store.register_agent("a1", "Version1", model="m1")
        original_registered = a1.registered_at
        time.sleep(0.01)
        a2 = store.register_agent("a1", "Version2", model="m2")
        # display_name and model should update
        assert a2.display_name == "Version2"
        assert a2.model == "m2"
        # registered_at should be preserved
        fetched = store.get_agent("a1")
        assert fetched.registered_at == original_registered


class TestGetAttachmentsDir:
    """T16 — Test get_attachments_dir()."""

    def test_creates_dir(self, session_mgr):
        s = session_mgr.create_session("att-test")
        d = session_mgr.get_attachments_dir(s.id)
        assert d.exists()
        assert d.is_dir()
        assert d.name == "attachments"


class TestSessionIdValidation:
    """Test M9 — session ID path traversal rejection."""

    def test_rejects_path_traversal(self, session_mgr):
        with pytest.raises(ValueError, match="path traversal"):
            session_mgr.get_store("../../../etc")

    def test_rejects_slash(self, session_mgr):
        with pytest.raises(ValueError, match="path traversal"):
            session_mgr.get_store("foo/bar")


class TestMessageValidation:
    """L6/L8/L15 — Test Message model validators."""

    def test_empty_sender_id_rejected(self):
        with pytest.raises(ValueError, match="sender_id must not be empty"):
            Message(sender_id="", sender_type=SenderType.AGENT, content="hello")

    def test_whitespace_sender_id_rejected(self):
        with pytest.raises(ValueError, match="sender_id must not be empty"):
            Message(sender_id="   ", sender_type=SenderType.AGENT, content="hello")

    def test_empty_content_rejected(self):
        with pytest.raises(ValueError, match="content must not be empty"):
            Message(sender_id="a1", sender_type=SenderType.AGENT, content="")

    def test_whitespace_content_rejected(self):
        with pytest.raises(ValueError, match="content must not be empty"):
            Message(sender_id="a1", sender_type=SenderType.AGENT, content="   ")

    def test_sender_id_length_limit(self):
        with pytest.raises(ValueError, match="exceeds"):
            Message(sender_id="x" * 300, sender_type=SenderType.AGENT, content="hi")

    def test_content_length_limit(self):
        from agent_chat.core.models import MAX_CONTENT_LENGTH
        with pytest.raises(ValueError, match="exceeds"):
            Message(sender_id="a1", sender_type=SenderType.AGENT, content="x" * (MAX_CONTENT_LENGTH + 1))

    def test_valid_message(self):
        msg = Message(sender_id="a1", sender_type=SenderType.AGENT, content="hello")
        assert msg.sender_id == "a1"
        assert msg.content == "hello"


class TestCreateChannelIdempotent:
    """M7 — create_channel returns existing on conflict."""

    def test_returns_existing(self, store):
        ch1 = store.create_channel("dev", "Development")
        ch2 = store.create_channel("dev", "Different description")
        assert ch1.id == ch2.id
        assert ch2.description == "Development"  # original preserved


class TestPollingEventBased:
    """F1/F2 — Test polling with event-based synchronization instead of sleep."""

    def test_polling_with_event(self, tmp_dir):
        mgr = SessionManager(tmp_dir / "sessions")
        session = mgr.create_session("event-poll")

        received = []
        received_event = threading.Event()

        def on_messages(msgs):
            received.extend(msgs)
            if msgs:
                received_event.set()

        c1 = AgentClient("a1", "Poller", session=session.id, base_dir=tmp_dir / "sessions")
        c2 = AgentClient("a2", "Sender", session=session.id, base_dir=tmp_dir / "sessions")

        c1.start_polling(callback=on_messages, interval=0.2)
        time.sleep(0.3)  # let initial empty poll complete

        c2.post_message("event-based test")

        # Wait up to 3 seconds for the message (vs arbitrary sleep)
        assert received_event.wait(timeout=3.0), "Polling did not pick up message in time"
        assert len(received) >= 1
        assert received[0].content == "event-based test"

        c1.stop_polling()
        c1.close()
        c2.close()
