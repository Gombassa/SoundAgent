import json
from datetime import datetime, timezone
from pathlib import Path


class IngestLog:
    def __init__(self, path: Path):
        self.path = path

    def write(
        self,
        filename: str,
        file_hash: str,
        source: str,
        status: str,
        **extra,
    ) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "filename": filename,
            "hash": file_hash,
            "source": source,
            "status": status,
            **extra,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
