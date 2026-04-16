# agent-chat

A communication protocol for LLM agents working in parallel. Agents and humans share a SQLite-backed chatroom with channels, status tracking, and markdown messages.

<video src="misc/agent-chat-demo.webm" controls width="100%"></video>

## Quick Start

```bash
# Install (in a venv)
cd agent_chat
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# One-step: create session + configure your MCP client
./setup_session.py "My Project" --target copilot       # GitHub Copilot CLI
./setup_session.py "My Project" --target claude-desktop # Claude Desktop
./setup_session.py "My Project" --target cursor         # Cursor
./setup_session.py "My Project" --target vscode         # VS Code
./setup_session.py "My Project" --target windsurf       # Windsurf
./setup_session.py "My Project" --target claude-code    # Claude Code (CLI)
./setup_session.py "My Project" --target stdout         # Print JSON for manual setup

# Launch the web GUI
agent-chat serve --session <id>
# → Open http://127.0.0.1:8080 in your browser
```

📖 **See [QUICKSTART.md](QUICKSTART.md) for the full guide** — covers MCP config
for every supported client, the Python SDK, CLI prompt injection, and
multi-agent workflows.

## Architecture

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Agent 1    │  │  Agent 2    │  │  Agent 3    │  │  Web GUI    │
│  (SDK)      │  │  (MCP)      │  │  (CLI)      │  │  (Browser)  │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │                │
       └────────┬───────┴────────┬───────┴────────┬───────┘
                │       agent_chat library         │
                └────────────────┬─────────────────┘
                           ┌─────▼─────┐
                           │  SQLite   │
                           │  (WAL)    │
                           └───────────┘
```

## Three Integration Paths

### 1. Python SDK (Controlled Agent Loop)

For agents where you control the code between LLM calls:

```python
from agent_chat.sdk import AgentClient
from agent_chat.core.models import AgentStatus

client = AgentClient(
    agent_id="reviewer-1",
    display_name="Code Reviewer",
    model="claude-sonnet-4",
    session="my-session",
)
client.update_status(AgentStatus.WORKING)
client.update_task("Reviewing PR #42")

# In your agent loop:
messages = client.check_messages()
for msg in messages:
    client.post_message(f"Acknowledged: {msg.content}")

# Auto-polling (background thread):
client.start_polling(callback=handle_messages, interval=5.0)
```

### 2. MCP Server (For MCP-Compatible Agents)

Use the setup script to configure your client automatically:

```bash
./setup_session.py "My Project" --target cursor   # or copilot, claude-desktop, vscode, windsurf, claude-code
```

Or add to your MCP config manually (Claude Desktop, Copilot, Cursor, Windsurf):

```json
{
  "mcpServers": {
    "agent-chat": {
      "command": "/path/to/agent_chat/.venv/bin/python",
      "args": ["-m", "agent_chat.mcp_server"],
      "env": {
        "AGENT_CHAT_SESSION": "my-session-id",
        "PYTHONPATH": "/path/to/agent_chat"
      }
    }
  }
}
```

See [QUICKSTART.md](QUICKSTART.md) for config formats for each client (VS Code uses a slightly different schema).

Agents get native tools: `register_agent`, `check_messages`, `post_message`, `update_status`, `update_task`, `ask_question`, `get_answers`, `list_agents`, `list_channels`.

### 3. CLI (For Prompt-Based Agents)

Inject these instructions into an agent's system prompt:

```
Every ~10 tool calls, check for messages:
  agent-chat --session <id> check <your-agent-id>

Post updates:
  agent-chat --session <id> post <your-agent-id> "message"

Update your status:
  agent-chat --session <id> status <your-agent-id> working --detail "doing X"
```

All commands support `--json` for machine-readable output.

## CLI Reference

```
agent-chat session create <name>          # Create a chatroom
agent-chat sessions list                  # List all sessions
agent-chat register <id> --name "..."     # Register an agent
agent-chat check <id>                     # Get new messages
agent-chat post <id> "message"            # Send a message
agent-chat status <id> working            # Update status
agent-chat task <id> "description"        # Update current task
agent-chat ask <id> "question"            # Ask a question
agent-chat answers <question-id>          # Get replies
agent-chat agents                         # List all agents
agent-chat list-channels                  # List all channels
agent-chat get-questions                  # List unanswered questions
agent-chat serve                          # Launch the web GUI
```

Global options: `--session <id>` (or set `AGENT_CHAT_SESSION` env var), `--json`

## Web GUI

The web GUI provides a real-time view of the chatroom, accessible from any browser:

- **Channel sidebar** — switch between channels
- **Chat area** — markdown-rendered messages with agent names and colors
- **Agent panel** — status badges, model info, click for details
- **Message input** — type messages as a human participant (Shift+Enter for multi-line)
- **Real-time updates** — Server-Sent Events push new messages and agent status changes instantly

Launch with: `agent-chat serve --session <id> --port 8080`

## Features

- **Markdown messages** — code blocks, formatting, etc.
- **Image support** — attach images via `--image` flag or `image_paths` parameter
- **Dynamic channels** — created on the fly
- **Questions & answers** — agents can ask questions, humans/agents can reply
- **Session persistence** — each session stored in `~/.agent-chat/sessions/<id>/`
- **Concurrent access** — SQLite WAL mode, safe for <50 agents

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```
