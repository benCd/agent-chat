"""Tests for the FastAPI web GUI server."""

import json
import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agent_chat.core.store import SessionManager
from agent_chat.web.server import create_app


@pytest.fixture
def web_client(tmp_dir):
    """Create an httpx AsyncClient connected to a test FastAPI app."""
    mgr = SessionManager(tmp_dir / "sessions")
    session = mgr.create_session("web-test")
    app = create_app(session.id, session_mgr=mgr)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestWebIndex:
    async def test_index_returns_html(self, web_client):
        async with web_client as client:
            r = await client.get("/")
            assert r.status_code == 200
            assert "text/html" in r.headers["content-type"]
            assert "agent-chat" in r.text


class TestWebSession:
    async def test_get_session(self, web_client):
        async with web_client as client:
            r = await client.get("/api/session")
            assert r.status_code == 200
            data = r.json()
            assert data["name"] == "web-test"
            assert "id" in data


class TestWebAgents:
    async def test_register_and_list(self, web_client):
        async with web_client as client:
            # Register
            r = await client.post("/api/agents", json={
                "id": "bot-1", "display_name": "Test Bot", "model": "gpt-4"
            })
            assert r.status_code == 200
            data = r.json()
            assert data["id"] == "bot-1"
            assert data["display_name"] == "Test Bot"

            # List
            r = await client.get("/api/agents")
            assert r.status_code == 200
            agents = r.json()
            assert len(agents) == 1
            assert agents[0]["id"] == "bot-1"

    async def test_update_status(self, web_client):
        async with web_client as client:
            await client.post("/api/agents", json={"id": "a1", "display_name": "Agent"})
            r = await client.put("/api/agents/a1/status", json={"status": "working", "detail": "Testing"})
            assert r.status_code == 200
            assert r.json()["status"] == "working"

    async def test_update_status_invalid(self, web_client):
        async with web_client as client:
            await client.post("/api/agents", json={"id": "a1", "display_name": "Agent"})
            r = await client.put("/api/agents/a1/status", json={"status": "bogus"})
            assert r.status_code == 400

    async def test_update_task(self, web_client):
        async with web_client as client:
            await client.post("/api/agents", json={"id": "a1", "display_name": "Agent"})
            r = await client.put("/api/agents/a1/task", json={"current_task": "reviewing"})
            assert r.status_code == 200
            assert r.json()["current_task"] == "reviewing"


class TestWebChannels:
    async def test_list_channels(self, web_client):
        async with web_client as client:
            r = await client.get("/api/channels")
            assert r.status_code == 200
            channels = r.json()
            assert any(c["name"] == "general" for c in channels)


class TestWebMessages:
    async def test_post_and_get(self, web_client):
        async with web_client as client:
            # Register sender first
            await client.post("/api/agents", json={"id": "bot-1", "display_name": "Bot"})

            # Post
            r = await client.post("/api/messages", json={
                "sender_id": "bot-1",
                "content": "Hello from web test",
                "channel": "general",
                "sender_type": "agent",
            })
            assert r.status_code == 200
            msg = r.json()
            assert msg["content"] == "Hello from web test"
            assert msg["sender_type"] == "agent"

            # Get
            r = await client.get("/api/messages", params={"channel": "general"})
            assert r.status_code == 200
            msgs = r.json()
            assert len(msgs) == 1
            assert msgs[0]["content"] == "Hello from web test"

    async def test_get_all_messages(self, web_client):
        async with web_client as client:
            await client.post("/api/agents", json={"id": "bot-1", "display_name": "Bot"})
            await client.post("/api/messages", json={
                "sender_id": "bot-1", "content": "msg1", "channel": "general"
            })
            await client.post("/api/messages", json={
                "sender_id": "bot-1", "content": "msg2", "channel": "dev"
            })

            r = await client.get("/api/messages/all")
            assert r.status_code == 200
            assert len(r.json()) == 2

    async def test_messages_since(self, web_client):
        async with web_client as client:
            await client.post("/api/agents", json={"id": "bot-1", "display_name": "Bot"})
            r1 = await client.post("/api/messages", json={
                "sender_id": "bot-1", "content": "first"
            })
            ts = r1.json()["timestamp"]

            await client.post("/api/messages", json={
                "sender_id": "bot-1", "content": "second"
            })

            r = await client.get("/api/messages", params={"channel": "general", "since": ts})
            msgs = r.json()
            assert len(msgs) == 1
            assert msgs[0]["content"] == "second"

    async def test_post_as_question(self, web_client):
        async with web_client as client:
            await client.post("/api/agents", json={"id": "bot-1", "display_name": "Bot"})
            r = await client.post("/api/messages", json={
                "sender_id": "bot-1",
                "content": "What is this?",
                "is_question": True,
            })
            assert r.status_code == 200
            assert r.json()["is_question"] is True

    async def test_invalid_sender_type(self, web_client):
        async with web_client as client:
            r = await client.post("/api/messages", json={
                "sender_id": "bot-1",
                "content": "bad type",
                "sender_type": "robot",
            })
            assert r.status_code == 400


class TestWebQuestions:
    async def test_ask_and_answer(self, web_client):
        async with web_client as client:
            await client.post("/api/agents", json={"id": "a1", "display_name": "Agent"})

            # Ask
            r = await client.post("/api/questions", json={
                "sender_id": "a1", "question": "What port?"
            })
            assert r.status_code == 200
            q_id = r.json()["id"]

            # List questions
            r = await client.get("/api/questions")
            assert len(r.json()) == 1

            # Answer
            r = await client.post(f"/api/questions/{q_id}/answers", json={
                "sender_id": "a1", "answer": "Use 8080"
            })
            assert r.status_code == 200

            # Get answers
            r = await client.get(f"/api/questions/{q_id}/answers")
            answers = r.json()
            assert len(answers) == 1
            assert answers[0]["content"] == "Use 8080"


class TestWebSSE:
    def test_sse_event_helper(self):
        """Test the _sse_event helper produces valid SSE format."""
        from agent_chat.web.server import _sse_event
        result = _sse_event("message", {"id": "1", "content": "hello"})
        assert result.startswith("event: message\n")
        assert "data: " in result
        assert result.endswith("\n\n")
        import json
        data_line = [l for l in result.split("\n") if l.startswith("data: ")][0]
        parsed = json.loads(data_line[6:])
        assert parsed["id"] == "1"
        assert parsed["content"] == "hello"
