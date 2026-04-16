"""Tests for the core store and SDK client."""

import tempfile
import threading
import time
from pathlib import Path

import pytest

from agent_chat.core.models import AgentStatus, SenderType
from agent_chat.core.store import MessageStore, SessionManager
from agent_chat.sdk.client import AgentClient


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def store(tmp_dir):
    s = MessageStore(tmp_dir / "test.db")
    yield s
    s.close()


@pytest.fixture
def session_mgr(tmp_dir):
    return SessionManager(tmp_dir / "sessions")


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
