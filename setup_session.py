#!/usr/bin/env python3
"""Setup an agent-chat session and configure MCP for your preferred client.

Supports: GitHub Copilot CLI, Claude Desktop, Claude Code, Cursor, Windsurf,
VS Code, or any MCP-compatible client via stdout / custom path.

Usage:
    # Interactive — choose your client
    ./setup_session.py "My Session"

    # Direct — specify a target
    ./setup_session.py "My Session" --target copilot
    ./setup_session.py "My Session" --target claude-desktop
    ./setup_session.py "My Session" --target cursor
    ./setup_session.py "My Session" --target claude-code

    # Print JSON snippet to stdout (paste into any config manually)
    ./setup_session.py "My Session" --target stdout

    # Custom config file path
    ./setup_session.py "My Session" --target cursor --config-path /other/dir/mcp.json

    # Force a new session even if one with the same name exists
    ./setup_session.py "PR Review" --new --target copilot
"""

import argparse
import json
import os
import platform
import sys
from pathlib import Path

# Ensure agent_chat is importable from the project root
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent_chat.core.store import SessionManager

VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"


# ── Target definitions ───────────────────────────────────────────────────────

def _claude_desktop_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    if system == "Windows":
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    # Linux / other
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _claude_code_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    if system == "Windows":
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


TARGETS: dict[str, dict] = {
    "copilot": {
        "name": "GitHub Copilot CLI",
        "config_path": (
            Path(os.environ.get("COPILOT_HOME", str(Path.home() / ".copilot")))
            / "mcp-config.json"
        ),
        "server_key": "mcpServers",
        "restart_hint": "Restart GitHub Copilot CLI to pick up the changes.",
    },
    "claude-desktop": {
        "name": "Claude Desktop",
        "config_path": _claude_desktop_config_path(),
        "server_key": "mcpServers",
        "restart_hint": "Restart Claude Desktop to pick up the changes.",
    },
    "claude-code": {
        "name": "Claude Code (CLI)",
        "config_path": _claude_code_config_path(),
        "server_key": "mcpServers",
        "restart_hint": "Run `claude mcp list` to verify, then start a new conversation.",
    },
    "cursor": {
        "name": "Cursor",
        "config_path": PROJECT_ROOT / ".cursor" / "mcp.json",
        "server_key": "mcpServers",
        "restart_hint": "Restart Cursor or reload the window (Cmd/Ctrl+Shift+P → Reload).",
    },
    "windsurf": {
        "name": "Windsurf",
        "config_path": Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
        "server_key": "mcpServers",
        "restart_hint": "Restart Windsurf to pick up the changes.",
    },
    "vscode": {
        "name": "VS Code (Copilot Chat)",
        "config_path": PROJECT_ROOT / ".vscode" / "mcp.json",
        "server_key": "servers",
        "extra_fields": {"type": "stdio"},
        "restart_hint": "Reload VS Code window (Cmd/Ctrl+Shift+P → Reload Window).",
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _python_cmd() -> str:
    """Return the best Python executable path for the MCP server."""
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def _build_server_entry(session_id: str, extra_fields: dict | None = None) -> dict:
    """Build the MCP server JSON entry for agent-chat."""
    entry = {
        "command": _python_cmd(),
        "args": ["-m", "agent_chat.mcp_server"],
        "env": {
            "AGENT_CHAT_SESSION": session_id,
            "PYTHONPATH": str(PROJECT_ROOT),
        },
    }
    if extra_fields:
        entry.update(extra_fields)
    return entry


def _load_config(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_config(path: Path, config: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")


def _get_or_create_session(args) -> "Session":
    mgr = SessionManager(args.base_dir)
    if args.new:
        session = mgr.create_session(args.name)
        print(f"✨ Created new session: {session.name} ({session.id})")
    else:
        existing = [s for s in mgr.list_sessions() if s.name == args.name]
        if existing:
            session = existing[-1]
            print(f"♻️  Reusing session: {session.name} ({session.id})")
        else:
            session = mgr.create_session(args.name)
            print(f"✨ Created new session: {session.name} ({session.id})")
    return session


def _interactive_target_selection() -> str:
    """Present an interactive menu and return the chosen target key."""
    print("\n🔧 Which client would you like to configure?\n")
    options = list(TARGETS.items()) + [
        ("stdout", {"name": "Print to stdout (manual setup)", "config_path": None}),
    ]
    for i, (key, info) in enumerate(options, 1):
        name = info["name"]
        marker = ""
        cfg = info.get("config_path")
        if cfg and cfg.exists():
            marker = "  ✓ config exists"
        print(f"  {i}. {name} [{key}]{marker}")

    print()
    try:
        choice = input("Enter number or target name: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        sys.exit(0)

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(options):
            return options[idx][0]
        print(f"Invalid choice: {choice}")
        sys.exit(1)

    if choice in TARGETS or choice == "stdout":
        return choice
    print(f"Unknown target: {choice!r}")
    sys.exit(1)


def configure_target(
    target_key: str,
    session_id: str,
    config_path_override: Path | None = None,
) -> tuple[Path | None, str]:
    """Write the MCP config for a specific target. Returns (config_path, restart_hint)."""
    if target_key == "stdout":
        entry = _build_server_entry(session_id)
        snippet = {"mcpServers": {"agent-chat": entry}}
        print("\n" + json.dumps(snippet, indent=2))
        return None, ""

    target = TARGETS[target_key]
    path = config_path_override or target["config_path"]
    server_key = target["server_key"]
    entry = _build_server_entry(session_id, target.get("extra_fields"))

    config = _load_config(path)
    if server_key not in config:
        config[server_key] = {}
    config[server_key]["agent-chat"] = entry
    _save_config(path, config)

    return path, target["restart_hint"]


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Setup an agent-chat session and configure MCP for your client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Supported targets:\n"
            + "\n".join(f"  {k:18s} {v['name']}" for k, v in TARGETS.items())
            + "\n  stdout             Print JSON to stdout for manual setup"
        ),
    )
    parser.add_argument(
        "name",
        nargs="?",
        default="default",
        help="Session name (default: 'default')",
    )
    parser.add_argument(
        "--target", "-t",
        choices=list(TARGETS.keys()) + ["stdout"],
        default=None,
        help="MCP client to configure (default: interactive selection)",
    )
    parser.add_argument(
        "--new",
        action="store_true",
        help="Always create a new session, even if one with this name exists",
    )
    parser.add_argument(
        "--config-path",
        type=str,
        default=None,
        help="Override the default config file path for the chosen target",
    )
    parser.add_argument(
        "--base-dir",
        type=str,
        default=None,
        help="Custom base directory for session storage",
    )
    args = parser.parse_args()

    # ── Session ──────────────────────────────────────────────────────────
    session = _get_or_create_session(args)

    # ── Target selection ─────────────────────────────────────────────────
    target = args.target or _interactive_target_selection()

    # ── Configure ────────────────────────────────────────────────────────
    override = Path(args.config_path) if args.config_path else None
    path, restart_hint = configure_target(target, session.id, override)

    # ── Summary ──────────────────────────────────────────────────────────
    if path:
        target_name = TARGETS.get(target, {}).get("name", target)
        print(f"\n📝 Updated {path}")
        print(f"   Client:  {target_name}")
        print(f"   Server:  agent-chat")
        print(f"   Session: {session.id} ({session.name})")
        print(f"   Python:  {_python_cmd()}")

    print(f"\n🚀 Next steps:")
    if restart_hint:
        print(f"   1. {restart_hint}")
    print(f"   2. Launch the web GUI to watch the chat:")
    print(f"      agent-chat serve --session {session.id}")
    print(f"   3. Or use the CLI:")
    print(f"      agent-chat --session {session.id} agents")


if __name__ == "__main__":
    main()
