"""Integration tests: multi-agent communication scenarios."""

import tempfile
import threading
import time
from pathlib import Path

import pytest

from agent_chat.core.models import AgentStatus, SenderType
from agent_chat.core.store import SessionManager
from agent_chat.sdk.client import AgentClient


@pytest.fixture
def session_env():
    """Create a temporary session environment for integration tests."""
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "sessions"
        mgr = SessionManager(base)
        session = mgr.create_session("integration-test")
        yield {"base_dir": base, "session_id": session.id, "manager": mgr}


class TestMultiAgentCommunication:
    def test_three_agents_broadcast(self, session_env):
        """Three agents can all see each other's messages."""
        clients = [
            AgentClient(f"agent-{i}", f"Agent {i}", model=f"model-{i}",
                        session=session_env["session_id"], base_dir=session_env["base_dir"])
            for i in range(3)
        ]

        # Each agent posts
        for i, c in enumerate(clients):
            c.post_message(f"Hello from Agent {i}")

        # Each agent checks and sees the other two
        for i, c in enumerate(clients):
            msgs = c.check_messages()
            assert len(msgs) == 2
            senders = {m.sender_id for m in msgs}
            assert c.agent_id not in senders

        for c in clients:
            c.close()

    def test_question_answer_workflow(self, session_env):
        """Agent asks a question, human answers, agent retrieves answer."""
        agent = AgentClient("worker", "Worker Bot", model="gpt-4",
                            session=session_env["session_id"], base_dir=session_env["base_dir"])
        human = AgentClient("human-1", "Alice", session=session_env["session_id"],
                            base_dir=session_env["base_dir"])

        # Agent asks
        q = agent.ask_question("What database should I use?")
        assert q.is_question

        # Human sees the question
        msgs = human.check_messages()
        assert len(msgs) == 1
        assert msgs[0].is_question

        # Human answers
        human.post_message("Use PostgreSQL", parent_id=q.id)

        # Agent gets the answer
        answers = agent.get_answers(q.id)
        assert len(answers) == 1
        assert "PostgreSQL" in answers[0].content

        agent.close()
        human.close()

    def test_status_tracking(self, session_env):
        """Agent status updates are visible to all."""
        c1 = AgentClient("worker-1", "Worker", session=session_env["session_id"],
                         base_dir=session_env["base_dir"])
        c2 = AgentClient("monitor", "Monitor", session=session_env["session_id"],
                         base_dir=session_env["base_dir"])

        c1.update_status(AgentStatus.WORKING, detail="Processing batch")
        c1.update_task("Reviewing files 1-50")

        agents = c2.list_agents()
        worker = next(a for a in agents if a.id == "worker-1")
        assert worker.status == AgentStatus.WORKING
        assert worker.current_task == "Reviewing files 1-50"

        c1.update_status(AgentStatus.DONE)
        agents = c2.list_agents()
        worker = next(a for a in agents if a.id == "worker-1")
        assert worker.status == AgentStatus.DONE

        c1.close()
        c2.close()

    def test_multi_channel(self, session_env):
        """Messages in different channels are isolated."""
        c1 = AgentClient("a1", "Agent 1", session=session_env["session_id"],
                         base_dir=session_env["base_dir"])
        c2 = AgentClient("a2", "Agent 2", session=session_env["session_id"],
                         base_dir=session_env["base_dir"])

        c1.post_message("General message", channel="general")
        c1.post_message("Debug message", channel="debug")

        general_msgs = c2.check_messages(channel="general")
        debug_msgs = c2.check_messages(channel="debug")

        assert len(general_msgs) == 1
        assert general_msgs[0].content == "General message"
        assert len(debug_msgs) == 1
        assert debug_msgs[0].content == "Debug message"

        c1.close()
        c2.close()

    def test_concurrent_agents_no_data_loss(self, session_env):
        """Multiple agents posting concurrently don't lose messages."""
        n_agents = 5
        n_messages = 20
        errors = []

        clients = [
            AgentClient(f"concurrent-{i}", f"Agent {i}",
                        session=session_env["session_id"], base_dir=session_env["base_dir"])
            for i in range(n_agents)
        ]

        def post_messages(client, count):
            try:
                for j in range(count):
                    client.post_message(f"msg-{j}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=post_messages, args=(c, n_messages))
            for c in clients
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

        all_msgs = clients[0].store.get_all_messages()
        assert len(all_msgs) == n_agents * n_messages

        for c in clients:
            c.close()

    def test_agent_identity_visible_in_messages(self, session_env):
        """Agent display names and models are preserved and queryable."""
        c1 = AgentClient("r1", "Reviewer", model="claude-sonnet-4",
                         current_task="Code review",
                         session=session_env["session_id"], base_dir=session_env["base_dir"])
        c2 = AgentClient("w1", "Writer", model="gpt-4o",
                         current_task="Writing docs",
                         session=session_env["session_id"], base_dir=session_env["base_dir"])

        agents = c1.list_agents()
        assert len(agents) == 2

        reviewer = next(a for a in agents if a.id == "r1")
        assert reviewer.display_name == "Reviewer"
        assert reviewer.model == "claude-sonnet-4"
        assert reviewer.current_task == "Code review"

        writer = next(a for a in agents if a.id == "w1")
        assert writer.display_name == "Writer"
        assert writer.model == "gpt-4o"

        c1.close()
        c2.close()

    def test_session_isolation(self, session_env):
        """Two different sessions don't share data."""
        mgr = session_env["manager"]
        s2 = mgr.create_session("other-session")

        c1 = AgentClient("a1", "Agent in S1", session=session_env["session_id"],
                         base_dir=session_env["base_dir"])
        c2 = AgentClient("a2", "Agent in S2", session=s2.id,
                         base_dir=session_env["base_dir"])

        c1.post_message("Only in session 1")

        # c2 is in a different session — should see no messages
        msgs = c2.check_messages()
        assert len(msgs) == 0

        # Each session has only its own agent
        assert len(c1.list_agents()) == 1
        assert len(c2.list_agents()) == 1

        c1.close()
        c2.close()
