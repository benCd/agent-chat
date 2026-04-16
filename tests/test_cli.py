"""Tests for the agent-chat CLI."""

import json

import pytest
from typer.testing import CliRunner

import agent_chat.cli as cli_module
from agent_chat.cli import app
from agent_chat.core.models import SenderType
from agent_chat.core.store import SessionManager

runner = CliRunner()


@pytest.fixture(autouse=True)
def _use_tmp_dir(tmp_path):
    """Route all CLI operations to a temp directory."""
    cli_module._base_dir_override = tmp_path / "sessions"
    yield
    cli_module._base_dir_override = None


def _create_session(name: str = "test") -> str:
    """Helper: create session, return its ID."""
    r = runner.invoke(app, ["session", "create", name])
    assert r.exit_code == 0
    return r.output.strip()


def _register(agent_id: str, name: str, sid: str, **kwargs) -> None:
    args = ["register", agent_id, "--name", name, "--session", sid]
    for k, v in kwargs.items():
        args.extend([f"--{k}", v])
    r = runner.invoke(app, args)
    assert r.exit_code == 0


# ── session create ───────────────────────────────────────────────────────────

class TestSessionCreate:
    def test_plain(self):
        r = runner.invoke(app, ["session", "create", "my-room"])
        assert r.exit_code == 0
        sid = r.output.strip()
        assert len(sid) > 0

    def test_json(self):
        r = runner.invoke(app, ["session", "create", "my-room", "--json"])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert data["name"] == "my-room"
        assert "id" in data
        assert "created_at" in data


# ── sessions list ────────────────────────────────────────────────────────────

class TestSessionsList:
    def test_empty(self):
        r = runner.invoke(app, ["sessions", "list"])
        assert r.exit_code == 0
        assert "No sessions" in r.output

    def test_plain(self):
        _create_session("alpha")
        _create_session("beta")
        r = runner.invoke(app, ["sessions", "list"])
        assert r.exit_code == 0
        assert "alpha" in r.output
        assert "beta" in r.output

    def test_json(self):
        _create_session("gamma")
        r = runner.invoke(app, ["sessions", "list", "--json"])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert len(data) == 1
        assert data[0]["name"] == "gamma"


# ── sessions open ────────────────────────────────────────────────────────────

class TestSessionsOpen:
    def test_placeholder(self):
        r = runner.invoke(app, ["sessions", "open", "abc123"])
        assert r.exit_code == 0
        assert "TUI" in r.output


# ── register ─────────────────────────────────────────────────────────────────

class TestRegister:
    def test_plain(self):
        sid = _create_session()
        r = runner.invoke(app, [
            "register", "bot-1", "--name", "Bot One", "--session", sid,
        ])
        assert r.exit_code == 0
        assert "Bot One" in r.output
        assert "bot-1" in r.output

    def test_json_with_all_opts(self):
        sid = _create_session()
        r = runner.invoke(app, [
            "register", "bot-1", "--name", "Bot One",
            "--model", "gpt-4", "--task", "Testing",
            "--session", sid, "--json",
        ])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert data["id"] == "bot-1"
        assert data["model"] == "gpt-4"
        assert data["task"] == "Testing"


# ── check ────────────────────────────────────────────────────────────────────

class TestCheck:
    def test_no_messages(self):
        sid = _create_session()
        _register("a1", "Agent 1", sid)
        r = runner.invoke(app, ["check", "a1", "--session", sid])
        assert r.exit_code == 0
        assert "No new messages" in r.output

    def test_sees_other_agent(self):
        sid = _create_session()
        _register("a1", "Agent 1", sid)
        _register("a2", "Agent 2", sid)
        runner.invoke(app, ["post", "a2", "Hello from a2", "--session", sid])
        r = runner.invoke(app, ["check", "a1", "--session", sid])
        assert r.exit_code == 0
        assert "Hello from a2" in r.output
        assert "[a2]" in r.output

    def test_json(self):
        sid = _create_session()
        _register("a1", "Agent 1", sid)
        _register("a2", "Agent 2", sid)
        runner.invoke(app, ["post", "a2", "Hi", "--session", sid])
        r = runner.invoke(app, ["check", "a1", "--session", sid, "--json"])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert len(data) == 1
        assert data[0]["content"] == "Hi"

    def test_channel_option(self):
        sid = _create_session()
        _register("a1", "Agent 1", sid)
        _register("a2", "Agent 2", sid)
        runner.invoke(app, [
            "post", "a2", "debug msg",
            "--channel", "debug", "--session", sid,
        ])
        r = runner.invoke(app, [
            "check", "a1", "--channel", "debug", "--session", sid,
        ])
        assert r.exit_code == 0
        assert "debug msg" in r.output


# ── post ─────────────────────────────────────────────────────────────────────

class TestPost:
    def test_plain(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        r = runner.invoke(app, ["post", "bot-1", "Hello world", "--session", sid])
        assert r.exit_code == 0
        assert "Posted:" in r.output

    def test_json(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        r = runner.invoke(app, [
            "post", "bot-1", "Hello world", "--session", sid, "--json",
        ])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert data["content"] == "Hello world"
        assert "id" in data

    def test_channel(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        r = runner.invoke(app, [
            "post", "bot-1", "debug info",
            "--channel", "debug", "--session", sid, "--json",
        ])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert data["channel"] == "debug"


# ── status ───────────────────────────────────────────────────────────────────

class TestStatus:
    def test_plain(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        r = runner.invoke(app, ["status", "bot-1", "working", "--session", sid])
        assert r.exit_code == 0
        assert "working" in r.output

    def test_json_with_detail(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        r = runner.invoke(app, [
            "status", "bot-1", "done",
            "--detail", "Finished work", "--session", sid, "--json",
        ])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert data["status"] == "done"
        assert data["task"] == "Finished work"

    def test_invalid_status(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        r = runner.invoke(app, ["status", "bot-1", "invalid", "--session", sid])
        assert r.exit_code != 0

    def test_all_statuses(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        for s in ("idle", "working", "waiting", "done"):
            r = runner.invoke(app, ["status", "bot-1", s, "--session", sid])
            assert r.exit_code == 0
            assert s in r.output


# ── task ─────────────────────────────────────────────────────────────────────

class TestTask:
    def test_plain(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        r = runner.invoke(app, [
            "task", "bot-1", "Working on feature X", "--session", sid,
        ])
        assert r.exit_code == 0
        assert "Working on feature X" in r.output

    def test_json(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        r = runner.invoke(app, [
            "task", "bot-1", "Feature X", "--session", sid, "--json",
        ])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert data["task"] == "Feature X"
        assert data["id"] == "bot-1"


# ── ask ──────────────────────────────────────────────────────────────────────

class TestAsk:
    def test_plain(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        r = runner.invoke(app, [
            "ask", "bot-1", "What port?", "--session", sid,
        ])
        assert r.exit_code == 0
        assert "Question posted:" in r.output

    def test_json(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        r = runner.invoke(app, [
            "ask", "bot-1", "What port?", "--session", sid, "--json",
        ])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert data["content"] == "What port?"
        assert "id" in data


# ── answers ──────────────────────────────────────────────────────────────────

class TestAnswers:
    def _ask_question(self, sid: str) -> str:
        r = runner.invoke(app, [
            "ask", "bot-1", "What port?", "--session", sid, "--json",
        ])
        return json.loads(r.output)["id"]

    def test_no_answers(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        qid = self._ask_question(sid)
        r = runner.invoke(app, ["answers", qid, "--session", sid])
        assert r.exit_code == 0
        assert "No answers" in r.output

    def test_with_answers(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        _register("bot-2", "Helper", sid)
        qid = self._ask_question(sid)
        # Post a reply through the store
        mgr = SessionManager(base_dir=cli_module._base_dir_override)
        store = mgr.get_store(sid)
        store.post_message(
            "bot-2", "Use port 8080",
            parent_id=qid, sender_type=SenderType.AGENT,
        )
        store.close()
        r = runner.invoke(app, ["answers", qid, "--session", sid])
        assert r.exit_code == 0
        assert "8080" in r.output
        assert "[bot-2]" in r.output

    def test_json(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        qid = self._ask_question(sid)
        r = runner.invoke(app, ["answers", qid, "--session", sid, "--json"])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert isinstance(data, list)


# ── agents ───────────────────────────────────────────────────────────────────

class TestAgents:
    def test_empty(self):
        sid = _create_session()
        r = runner.invoke(app, ["agents", "--session", sid])
        assert r.exit_code == 0
        assert "No agents" in r.output

    def test_plain(self):
        sid = _create_session()
        _register("bot-1", "Bot One", sid, model="gpt-4")
        r = runner.invoke(app, ["agents", "--session", sid])
        assert r.exit_code == 0
        assert "bot-1" in r.output
        assert "gpt-4" in r.output

    def test_json(self):
        sid = _create_session()
        _register("bot-1", "Bot One", sid)
        r = runner.invoke(app, ["agents", "--session", sid, "--json"])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert len(data) == 1
        assert data[0]["id"] == "bot-1"
        assert data[0]["name"] == "Bot One"

    def test_shows_status_and_task(self):
        sid = _create_session()
        _register("bot-1", "Bot", sid)
        runner.invoke(app, [
            "status", "bot-1", "working",
            "--detail", "Reviewing PR", "--session", sid,
        ])
        r = runner.invoke(app, ["agents", "--session", sid, "--json"])
        data = json.loads(r.output)
        assert data[0]["status"] == "working"
        assert data[0]["task"] == "Reviewing PR"


# ── serve-mcp ────────────────────────────────────────────────────────────────

class TestServeMcp:
    def test_placeholder(self):
        r = runner.invoke(app, ["serve-mcp"])
        assert r.exit_code == 0
        assert "not yet implemented" in r.output.lower()
