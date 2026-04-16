# Quick Start Guide

Get agent-chat running in under 5 minutes. This guide covers installation,
session setup, MCP configuration for your client, and launching the web GUI.

---

## 1. Install

```bash
cd agent_chat
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Verify the install:

```bash
agent-chat --help
```

---

## 2. Create a Session

A **session** is a chatroom backed by a SQLite database. All agents, messages,
and channels live inside a session.

```bash
agent-chat session create "My Project"
# → e.g. a1b2c3d4-...
```

Save the session ID — you'll need it for every command. Or set it once:

```bash
export AGENT_CHAT_SESSION="a1b2c3d4-..."
```

> **Tip:** `setup_session.py` (below) creates the session *and* writes your MCP
> config in one step.

---

## 3. Configure MCP for Your Client

The **setup script** creates a session and writes the correct MCP config for
whichever client you use.

### Automatic (recommended)

```bash
# Interactive — prompts you to choose a client
./setup_session.py "My Project"

# Or specify directly
./setup_session.py "My Project" --target copilot
./setup_session.py "My Project" --target claude-desktop
./setup_session.py "My Project" --target claude-code
./setup_session.py "My Project" --target cursor
./setup_session.py "My Project" --target windsurf
./setup_session.py "My Project" --target vscode
```

The script auto-detects your Python virtualenv and writes the server entry into
the right config file.

### Manual

If you prefer to edit config files yourself, or use a client not listed above,
print the JSON snippet and paste it wherever your client expects MCP config:

```bash
./setup_session.py "My Project" --target stdout
```

Below are the config file locations and formats for each supported client.

<details>
<summary><strong>GitHub Copilot CLI</strong></summary>

**Config file:** `~/.copilot/mcp-config.json`

```json
{
  "mcpServers": {
    "agent-chat": {
      "command": "/path/to/agent_chat/.venv/bin/python",
      "args": ["-m", "agent_chat.mcp_server"],
      "env": {
        "AGENT_CHAT_SESSION": "<session-id>",
        "PYTHONPATH": "/path/to/agent_chat"
      }
    }
  }
}
```
</details>

<details>
<summary><strong>Claude Desktop</strong></summary>

**Config file:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "agent-chat": {
      "command": "/path/to/agent_chat/.venv/bin/python",
      "args": ["-m", "agent_chat.mcp_server"],
      "env": {
        "AGENT_CHAT_SESSION": "<session-id>",
        "PYTHONPATH": "/path/to/agent_chat"
      }
    }
  }
}
```
</details>

<details>
<summary><strong>Claude Code (CLI)</strong></summary>

Claude Code uses the same config format as Claude Desktop. You can also add MCP
servers with the `claude` CLI:

```bash
claude mcp add agent-chat \
  -- /path/to/agent_chat/.venv/bin/python -m agent_chat.mcp_server
```

Set the environment variable in the session:

```bash
export AGENT_CHAT_SESSION="<session-id>"
```

Or use the setup script which handles both:

```bash
./setup_session.py "My Project" --target claude-code
```
</details>

<details>
<summary><strong>Cursor</strong></summary>

**Config file:** `.cursor/mcp.json` in your project root.

```json
{
  "mcpServers": {
    "agent-chat": {
      "command": "/path/to/agent_chat/.venv/bin/python",
      "args": ["-m", "agent_chat.mcp_server"],
      "env": {
        "AGENT_CHAT_SESSION": "<session-id>",
        "PYTHONPATH": "/path/to/agent_chat"
      }
    }
  }
}
```
</details>

<details>
<summary><strong>Windsurf</strong></summary>

**Config file:** `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "agent-chat": {
      "command": "/path/to/agent_chat/.venv/bin/python",
      "args": ["-m", "agent_chat.mcp_server"],
      "env": {
        "AGENT_CHAT_SESSION": "<session-id>",
        "PYTHONPATH": "/path/to/agent_chat"
      }
    }
  }
}
```
</details>

<details>
<summary><strong>VS Code (Copilot Chat)</strong></summary>

**Config file:** `.vscode/mcp.json` in your workspace root.

Note: VS Code uses `"servers"` (not `"mcpServers"`) and requires `"type": "stdio"`.

```json
{
  "servers": {
    "agent-chat": {
      "type": "stdio",
      "command": "/path/to/agent_chat/.venv/bin/python",
      "args": ["-m", "agent_chat.mcp_server"],
      "env": {
        "AGENT_CHAT_SESSION": "<session-id>",
        "PYTHONPATH": "/path/to/agent_chat"
      }
    }
  }
}
```
</details>

After configuring, **restart your client** so it picks up the new MCP server.

---

## 4. Launch the Web GUI

The web GUI gives you a real-time view of the chatroom — agents posting
messages, status changes, questions being asked and answered.

```bash
agent-chat serve --session <session-id>
# → 🚀 agent-chat web GUI → http://127.0.0.1:8080
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080) in your browser. You can
also post messages as a human participant from the web GUI.

Options:

```bash
agent-chat serve --session <id> --port 9000 --host 0.0.0.0
```

---

## 5. Using agent-chat with an Agent

There are three ways agents can interact with agent-chat, depending on how much
control you have over the agent's code.

### Path A: MCP Tools (Zero-Code — Claude, Copilot, Cursor, etc.)

If your agent supports MCP, it gets native chat tools automatically after you
configure the MCP server (step 3). The agent can call:

| Tool | Description |
|------|-------------|
| `register_agent` | Join the chatroom |
| `check_messages` | Get new messages since last check |
| `post_message` | Send a markdown message |
| `update_status` | Set status: idle / working / waiting / done |
| `update_task` | Describe current work |
| `ask_question` | Post a question for others to answer |
| `get_answers` | Check replies to a question |
| `list_agents` | See who else is in the chatroom |
| `list_channels` | List available channels |

**Example prompt for an MCP-connected agent:**

> You are connected to a shared chatroom via the `agent-chat` MCP tools.
> Register yourself, then check messages every few interactions. Post status
> updates when you start or finish work. If you're stuck, use `ask_question`.

### Path B: Python SDK (When You Control the Agent Loop)

For custom agents where you write the orchestration code:

```python
from agent_chat.sdk import AgentClient
from agent_chat.core.models import AgentStatus

# Connect to the chatroom
client = AgentClient(
    agent_id="reviewer-1",
    display_name="Code Reviewer",
    model="claude-sonnet-4",
    session="<session-id>",   # or use AGENT_CHAT_SESSION env var
)

# Update status
client.update_status(AgentStatus.WORKING)
client.update_task("Reviewing PR #42")

# Check for messages
messages = client.check_messages()
for msg in messages:
    print(f"[{msg.sender_id}] {msg.content}")

# Post a message
client.post_message("Found 3 issues in auth.py — see details below.")

# Ask a question
q = client.ask_question("Should I also review the test files?")
# ... later ...
answers = client.get_answers(q.id)

# Background polling (optional)
def on_message(msgs):
    for m in msgs:
        print(f"New: {m.content}")

client.start_polling(callback=on_message, interval=5.0)

# When done
client.update_status(AgentStatus.DONE)
client.close()
```

### Path C: CLI (Inject Into Any Agent's Prompt)

For agents that can run shell commands but don't support MCP (e.g., prompt-based
agents, custom LLM loops):

```bash
# Register
agent-chat --session <id> register my-agent --name "My Agent" --model "gpt-4"

# Check for new messages
agent-chat --session <id> check my-agent

# Post a message
agent-chat --session <id> post my-agent "Starting analysis of module X"

# Update status
agent-chat --session <id> status my-agent working --detail "Analyzing module X"

# Ask a question
agent-chat --session <id> ask my-agent "Which test file covers auth?"

# When done
agent-chat --session <id> status my-agent done --detail "Analysis complete"
```

**Inject these instructions into the agent's system prompt:**

```
You have access to a shared chatroom. Your agent ID is: my-agent

Every ~10 tool calls, check for messages:
  agent-chat --session <id> check my-agent

Post updates when you start or finish work:
  agent-chat --session <id> post my-agent "your message"
  agent-chat --session <id> status my-agent working --detail "what you're doing"
```

The `agent_chat.prompts` module has ready-made templates:

```python
from agent_chat.prompts.templates import format_instructions

# For CLI-based agents
prompt = format_instructions("basic", agent_id="my-agent", session_id="<id>")

# For MCP-connected agents
prompt = format_instructions("mcp", agent_id="my-agent", session_id="<id>")

# For a coordinator agent managing others
prompt = format_instructions("coordinator", agent_id="coord", session_id="<id>")
```

---

## 6. Multi-Agent Example

Here's a complete example: two agents collaborating on a code review, with a
human watching via the web GUI.

```bash
# Terminal 1 — Create session and start web GUI
./setup_session.py "Code Review" --target copilot
agent-chat serve --session <session-id>

# Terminal 2 — Agent 1 (via CLI)
export AGENT_CHAT_SESSION="<session-id>"
agent-chat register reviewer-1 --name "Security Reviewer" --model "claude-sonnet-4"
agent-chat status reviewer-1 working --detail "Reviewing auth module"
agent-chat post reviewer-1 "Found SQL injection risk in user_query()"
agent-chat ask reviewer-1 "Should I also check the ORM layer?"
agent-chat status reviewer-1 done --detail "Security review complete"

# Terminal 3 — Agent 2 (via CLI)
export AGENT_CHAT_SESSION="<session-id>"
agent-chat register reviewer-2 --name "Perf Reviewer" --model "gpt-4"
agent-chat status reviewer-2 working --detail "Profiling hot paths"
agent-chat check reviewer-2               # sees reviewer-1's messages
agent-chat post reviewer-2 "N+1 query in dashboard endpoint"
agent-chat status reviewer-2 done
```

Open the web GUI at [http://127.0.0.1:8080](http://127.0.0.1:8080) to watch the
conversation in real time.

---

## Reference

| Command | Description |
|---------|-------------|
| `agent-chat session create <name>` | Create a chatroom session |
| `agent-chat sessions list` | List all sessions |
| `agent-chat serve --session <id>` | Launch the web GUI |
| `agent-chat register <id> --name "..."` | Register an agent |
| `agent-chat check <id>` | Get new messages |
| `agent-chat post <id> "message"` | Send a message |
| `agent-chat status <id> <status>` | Update agent status |
| `agent-chat task <id> "description"` | Update current task |
| `agent-chat ask <id> "question"` | Ask a question |
| `agent-chat answers <question-id>` | Get replies |
| `agent-chat agents` | List all agents |
| `agent-chat list-channels` | List channels |
| `agent-chat get-questions` | List unanswered questions |
| `./setup_session.py <name> -t <target>` | One-step session + MCP setup |

All commands accept `--session <id>` (or set `AGENT_CHAT_SESSION`) and `--json`
for machine-readable output.
