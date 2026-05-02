import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SourceConfig:
    name: str
    type: str       # local | network | rclone | webdav
    enabled: bool
    options: dict   # all remaining type-specific keys


@dataclass
class Config:
    library_root: Path
    basehead_import_path: Path
    tick_interval: int
    log_level: str
    sources: list[SourceConfig]
    anthropic_api_key: str
    audio_analysis: dict
    raw: dict


def load_config(path: str = "config.yaml") -> Config:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path.resolve()}")

    with open(cfg_path) as f:
        raw: dict = yaml.safe_load(f)

    # env var overrides
    if v := os.environ.get("SOUNDAGENT_LIBRARY_ROOT"):
        raw["library_root"] = v
    if v := os.environ.get("SOUNDAGENT_BASEHEAD_IMPORT_PATH"):
        raw["basehead_import_path"] = v

    if "library_root" not in raw:
        raise ValueError("Config missing required key: library_root")
    if "basehead_import_path" not in raw:
        raise ValueError("Config missing required key: basehead_import_path")

    sources = []
    for entry in raw.get("sources", []):
        entry = dict(entry)   # copy so we don't mutate the raw dict
        sources.append(SourceConfig(
            name=entry.pop("name"),
            type=entry.pop("type"),
            enabled=entry.pop("enabled", True),
            options=entry,
        ))

    return Config(
        library_root=Path(raw["library_root"]),
        basehead_import_path=Path(raw["basehead_import_path"]),
        tick_interval=int(raw.get("tick_interval", 300)),
        log_level=raw.get("log_level", "INFO"),
        sources=sources,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", raw.get("anthropic_api_key", "")),
        audio_analysis=raw.get("audio_analysis", {}),
        raw=raw,
    )
