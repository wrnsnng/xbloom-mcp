"""xbloom-mcp: brew on an xBloom Studio from Claude."""

import sys

USAGE = """usage: xbloom-mcp [command]

  serve        run the MCP server (default)
  run-all      run the server and the Cloudflare tunnel, restarting them if they exit
  setup        interactive first-time setup (safe to re-run)
  check        restart the server and test the connection to the machine
  rotate-key   issue a new connector key (the old one stops working)
  uninstall    remove the autostart (add --all to delete recipes and settings too)
"""


def main() -> None:
    from .config import load_settings_into_env

    load_settings_into_env()
    args = sys.argv[1:]
    cmd = args[0] if args else "serve"
    if cmd == "serve":
        from .server import serve
        serve()
    elif cmd == "run-all":
        from .supervisor import main as run_all
        run_all()
    elif cmd in ("setup", "check", "rotate-key", "uninstall"):
        from . import setup_cli
        if cmd == "setup":
            setup_cli.setup()
        elif cmd == "check":
            setup_cli.check()
        elif cmd == "rotate-key":
            setup_cli.rotate_key()
        else:
            setup_cli.uninstall(everything="--all" in args)
    else:
        print(USAGE)
        sys.exit(0 if cmd in ("-h", "--help", "help") else 2)
