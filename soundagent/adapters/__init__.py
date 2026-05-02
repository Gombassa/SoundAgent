from soundagent.adapters.base import BaseAdapter
from soundagent.config import Config, SourceConfig


def get_adapter(cfg: Config, source: SourceConfig) -> BaseAdapter:
    if source.type == "local":
        from soundagent.adapters.local import LocalAdapter
        return LocalAdapter(cfg, source)
    if source.type == "network":
        from soundagent.adapters.local import NetworkAdapter
        return NetworkAdapter(cfg, source)
    if source.type == "rclone":
        from soundagent.adapters.rclone import RcloneAdapter
        return RcloneAdapter(cfg, source)
    if source.type == "webdav":
        from soundagent.adapters.webdav import WebDAVAdapter
        return WebDAVAdapter(cfg, source)
    raise ValueError(f"Unknown adapter type: {source.type!r} (source: {source.name!r})")
