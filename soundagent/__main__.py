import argparse
import sys

from soundagent.config import load_config
from soundagent.logging_setup import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="soundagent")
    parser.add_argument("--config", default="config.yaml", metavar="PATH")
    sub = parser.add_subparsers(dest="command", required=True)

    tick_cmd = sub.add_parser("tick", help="Run one agent tick")
    tick_cmd.add_argument("--dry-run", action="store_true")

    sub.add_parser("init", help="Create library folder hierarchy")

    webdav_cmd = sub.add_parser("webdav", help="Manage the WebDAV server")
    webdav_sub = webdav_cmd.add_subparsers(dest="webdav_action", required=True)
    webdav_sub.add_parser("start", help="Start WebDAV server as background process")
    webdav_sub.add_parser("stop", help="Stop WebDAV server")
    webdav_sub.add_parser("status", help="Show WebDAV server status")
    webdav_sub.add_parser("_serve", help=argparse.SUPPRESS)   # internal — called by start

    query_cmd = sub.add_parser("query", help="Search the catalogue (Phase 6)")
    query_cmd.add_argument("--tag")
    query_cmd.add_argument("--category")

    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    setup_logging(cfg)

    if args.command == "tick":
        from soundagent.tick import run_tick
        sys.exit(run_tick(cfg, dry_run=args.dry_run))

    elif args.command == "init":
        from soundagent.init_library import init_library
        init_library(cfg)

    elif args.command == "webdav":
        from soundagent import webdav_server
        if args.webdav_action == "start":
            webdav_server.start(cfg)
        elif args.webdav_action == "stop":
            webdav_server.stop(cfg)
        elif args.webdav_action == "status":
            running = webdav_server.is_running(cfg)
            print("WebDAV server: running" if running else "WebDAV server: stopped")
        elif args.webdav_action == "_serve":
            webdav_server.serve(cfg)

    elif args.command == "query":
        print("Query interface not yet implemented (Phase 6)", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
