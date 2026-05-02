import logging
from pathlib import Path

from soundagent.adapters.base import BaseAdapter

log = logging.getLogger("soundagent.adapter.webdav")


class WebDAVAdapter(BaseAdapter):
    """
    Passive adapter — the wsgidav server runs as a persistent background
    process (managed via `python -m soundagent webdav start/stop`).
    collect() simply returns files that have landed in inbox since the
    last tick; it does not start or stop the server.
    """

    def is_available(self) -> bool:
        from soundagent.webdav_server import is_running
        return is_running(self.cfg)

    def collect(self, dry_run: bool = False) -> list[Path]:
        if not self.is_available():
            log.warning(
                f"[{self.name}] WebDAV server is not running. "
                "Start it with: python -m soundagent webdav start"
            )
            return []
        files = [f for f in self.inbox.iterdir() if f.is_file() and not f.name.startswith(".")]
        log.info(f"[{self.name}] {len(files)} file(s) found in inbox via WebDAV")
        return files
