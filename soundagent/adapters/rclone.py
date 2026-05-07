import logging
import subprocess
from pathlib import Path

from soundagent.adapters.base import BaseAdapter

log = logging.getLogger("soundagent.adapter.rclone")

_RCLONE_TIMEOUT = 300  # seconds


class RcloneAdapter(BaseAdapter):

    @property
    def _remote(self) -> str:
        return f"{self.source.options['remote']}:{self.source.options.get('remote_path', '/')}"

    def is_available(self) -> bool:
        try:
            r = subprocess.run(
                ["rclone", "lsd", self._remote, "--max-depth", "0"],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=10,
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def collect(self, dry_run: bool = False) -> list[Path]:
        mode = self.source.options.get("mode", "sync")
        if mode == "mount":
            log.warning(f"[{self.name}] Mount mode not yet implemented — falling back to copy")

        before = {f.name for f in self.inbox.iterdir() if f.is_file()} if self.inbox.exists() else set()

        flags = ["--dry-run"] if dry_run else []
        cmd = ["rclone", "copy", self._remote, str(self.inbox)] + flags

        log.info(f"[{self.name}] {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, capture_output=True, stdin=subprocess.DEVNULL, text=True, timeout=_RCLONE_TIMEOUT)
        except FileNotFoundError:
            log.error(f"[{self.name}] rclone not found on PATH")
            return []
        except subprocess.CalledProcessError as e:
            log.error(f"[{self.name}] rclone failed: {e.stderr.strip()}")
            return []
        except subprocess.TimeoutExpired:
            log.error(f"[{self.name}] rclone timed out after {_RCLONE_TIMEOUT}s")
            return []

        if dry_run:
            return []

        return [f for f in self.inbox.iterdir() if f.is_file() and f.name not in before]
