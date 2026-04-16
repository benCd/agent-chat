#!/usr/bin/env python3
"""Setup or refresh an agent-chat session and configure the Copilot CLI MCP entry.

Usage:
    # Create a new session and configure MCP
    ./setup_session.py "My Collab Session"

    # Create with defaults (session named "default")
    ./setup_session.py

    # Force a new session even if one with the same name exists
    ./setup_session.py "PR Review" --new
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure agent_chat is importable from the project root
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent_chat.core.store import SessionManager

COPILOT_HOME = Path(os.environ.get("COPILOT_HOME", Path.home() / ".copilot"))
"""Path to the Copilot home directory.

Reads from the ``COPILOT_HOME`` environment variable.  Falls back to
``~/.copilot`` when the variable is unset.  This is where
``mcp-config.json`` is stored.
"""
MCP_CONFIG_PATH = COPILOT_HOME / "mcp-config.json"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"


def load_mcp_config() -> dict:
    if MCP_CONFIG_PATH.exists():
        return json.loads(MCP_CONFIG_PATH.read_text())
    return {}


def save_mcp_config(config: dict):
    MCP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    MCP_CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Setup an agent-chat session for Copilot CLI")
    parser.add_argument("name", nargs="?", default="default", help="Session name (default: 'default')")
    parser.add_argument("--new", action="store_true", help="Always create a new session, even if one with this name exists")
    parser.add_argument("--base-dir", type=str, default=None, help="Custom base directory for sessions")
    args = parser.parse_args()

    mgr = SessionManager(args.base_dir)

    if args.new:
        session = mgr.create_session(args.name)
        print(f"✨ Created new session: {session.name} ({session.id})")
    else:
        # Reuse existing session with same name, or create
        existing = [s for s in mgr.list_sessions() if s.name == args.name]
        if existing:
            session = existing[-1]  # most recent
            print(f"♻️  Reusing session: {session.name} ({session.id})")
        else:
            session = mgr.create_session(args.name)
            print(f"✨ Created new session: {session.name} ({session.id})")

    # Determine the python executable to use
    python_cmd = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

    # Update MCP config
    config = load_mcp_config()
    if "mcpServers" not in config:
        config["mcpServers"] = {}

    config["mcpServers"]["agent-chat"] = {
        "command": python_cmd,
        "args": ["-m", "agent_chat.mcp_server"],
        "env": {
            "AGENT_CHAT_SESSION": session.id,
            "PYTHONPATH": str(PROJECT_ROOT),
        },
    }

    save_mcp_config(config)

    print(f"\n📝 Updated {MCP_CONFIG_PATH}")
    print(f"   Server:  agent-chat")
    print(f"   Session: {session.id} ({session.name})")
    print(f"   Python:  {python_cmd}")
    print(f"\n🚀 Restart Copilot CLI to pick up the changes.")
    print(f"   You can also launch the web GUI to watch the chat:")
    print(f"   cd {PROJECT_ROOT} && source .venv/bin/activate")
    print(f"   agent-chat serve --session {session.id}")


if __name__ == "__main__":
    main()
