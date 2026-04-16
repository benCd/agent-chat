"""Allow running the package with ``python -m agent_chat``."""

import sys


def main():
    if "--mcp" in sys.argv:
        sys.argv.remove("--mcp")
        from .mcp_server import main as mcp_main
        mcp_main()
    else:
        from .cli import app
        app()


if __name__ == "__main__":
    main()
