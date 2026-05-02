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

    elif args.command == "query":
        print("Query interface not yet implemented (Phase 6)", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
