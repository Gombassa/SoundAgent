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

    query_cmd = sub.add_parser("query", help="Search the sound catalogue")
    query_cmd.add_argument("terms", nargs="*", metavar="TERM",
                           help="Full-text search terms (description / tags)")
    query_cmd.add_argument("--category", metavar="CAT")
    query_cmd.add_argument("--subcategory", metavar="SUB")
    query_cmd.add_argument("--source", metavar="ADAPTER")
    query_cmd.add_argument("--min-duration", type=float, metavar="S")
    query_cmd.add_argument("--max-duration", type=float, metavar="S")
    query_cmd.add_argument("--min-bpm", type=float, metavar="BPM")
    query_cmd.add_argument("--max-bpm", type=float, metavar="BPM")
    query_cmd.add_argument("--limit", type=int, default=50, metavar="N")
    query_cmd.add_argument("--json", action="store_true", dest="as_json",
                           help="Output raw JSON")

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
        from soundagent.catalogue import open_catalogue
        cat = open_catalogue(cfg.library_root)
        fts_query = " ".join(args.terms) if args.terms else None
        results = cat.search(
            query=fts_query,
            category=args.category,
            subcategory=args.subcategory,
            source=args.source,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            min_bpm=args.min_bpm,
            max_bpm=args.max_bpm,
            limit=args.limit,
        )
        cat.close()

        if args.as_json:
            import json as _json
            print(_json.dumps(results, indent=2))
        else:
            if not results:
                print("No results.")
                sys.exit(0)
            for r in results:
                tags = ", ".join(r.get("tags") or [])
                bpm = f"  {r['bpm']:.0f}bpm" if r.get("bpm") else ""
                dur = f"  {r['duration_s']:.1f}s" if r.get("duration_s") else ""
                print(
                    f"{r['filename']}"
                    f"  [{r.get('cat_id') or r.get('category', '?')}]{bpm}{dur}"
                    f"  {r.get('description', '')}"
                )
                if tags:
                    print(f"    tags: {tags}")


if __name__ == "__main__":
    main()
