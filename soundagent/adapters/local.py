import logging
import shutil
from pathlib import Path

from soundagent.adapters.base import BaseAdapter

log = logging.getLogger("soundagent.adapter.local")


class LocalAdapter(BaseAdapter):

    @property
    def _source_path(self) -> Path:
        return Path(self.source.options["path"])

    def is_available(self) -> bool:
        return self._source_path.exists()

    def collect(self, dry_run: bool = False) -> list[Path]:
        src = self._source_path
        if not src.exists():
            log.warning(f"[{self.name}] Source path not found: {src}")
            return []

        same_dir = src.resolve() == self.inbox.resolve()
        collected: list[Path] = []

        for f in src.rglob("*"):
            if not f.is_file() or f.name.startswith("."):
                continue
            if same_dir:
                collected.append(f)
                continue
            dest = self.inbox / f.name
            if dry_run:
                log.info(f"[{self.name}] [dry-run] would copy {f.name} → inbox")
                collected.append(dest)
                continue
            tmp = self.inbox / f".{f.name}.tmp"
            shutil.copy2(f, tmp)
            tmp.replace(dest)
            log.info(f"[{self.name}] Collected {f.name}")
            collected.append(dest)

        return collected


class NetworkAdapter(LocalAdapter):
    """LocalAdapter with an availability guard for mapped/mounted network paths."""

    def is_available(self) -> bool:
        try:
            return self._source_path.exists()
        except OSError:
            return False

    def collect(self, dry_run: bool = False) -> list[Path]:
        if not self.is_available():
            log.warning(f"[{self.name}] Network path unavailable: {self._source_path}")
            return []
        return super().collect(dry_run)
