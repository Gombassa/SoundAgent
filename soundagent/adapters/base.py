from abc import ABC, abstractmethod
from pathlib import Path

from soundagent.config import Config, SourceConfig


class BaseAdapter(ABC):
    def __init__(self, cfg: Config, source: SourceConfig):
        self.cfg = cfg
        self.source = source

    @property
    def name(self) -> str:
        return self.source.name

    @property
    def inbox(self) -> Path:
        return self.cfg.library_root / "_inbox"

    def is_available(self) -> bool:
        return True

    @abstractmethod
    def collect(self, dry_run: bool = False) -> list[Path]:
        """Deliver new files into inbox. Returns paths of files now in inbox."""
        ...
