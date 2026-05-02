"""
WebDAV server lifecycle: start, stop, status.

The server runs as a persistent background subprocess (independent of ticks)
so mobile devices can drop files at any time. The PID is written to
<library_root>/webdav.pid. The tick's WebDAV adapter reads files that have
landed in _inbox/ since the server started.
"""

import logging
import os
import platform
import subprocess
import sys
from pathlib import Path

from soundagent.config import Config

log = logging.getLogger("soundagent.webdav")


def _pid_file(cfg: Config) -> Path:
    return cfg.library_root / "webdav.pid"


def is_running(cfg: Config) -> bool:
    pf = _pid_file(cfg)
    if not pf.exists():
        return False
    try:
        pid = int(pf.read_text().strip())
    except (ValueError, OSError):
        return False
    return _process_alive(pid)


def _process_alive(pid: int) -> bool:
    if platform.system() == "Windows":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True,
        )
        return str(pid) in result.stdout
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def start(cfg: Config) -> None:
    if is_running(cfg):
        log.info("WebDAV server already running")
        return

    proc = subprocess.Popen(
        [sys.executable, "-m", "soundagent", "--config", "config.yaml", "webdav", "_serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS if platform.system() == "Windows" else 0,
    )
    _pid_file(cfg).write_text(str(proc.pid))
    source = next((s for s in cfg.sources if s.type == "webdav" and s.enabled), None)
    port = source.options.get("port", 8080) if source else 8080
    log.info(f"WebDAV server started (PID {proc.pid}) on port {port}")
    log.info(f"Connect from iOS: Files → Browse → ··· → Connect to Server → http://<machine-ip>:{port}")


def stop(cfg: Config) -> None:
    pf = _pid_file(cfg)
    if not pf.exists():
        log.info("WebDAV server not running (no PID file)")
        return
    try:
        pid = int(pf.read_text().strip())
    except (ValueError, OSError):
        pf.unlink(missing_ok=True)
        return

    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, 15)  # SIGTERM
        except (OSError, ProcessLookupError):
            pass

    pf.unlink(missing_ok=True)
    log.info(f"WebDAV server stopped (PID {pid})")


def serve(cfg: Config) -> None:
    """Blocking server loop — called by the _serve subcommand."""
    source = next((s for s in cfg.sources if s.type == "webdav" and s.enabled), None)
    if source is None:
        log.error("No enabled webdav source in config")
        return

    port = int(source.options.get("port", 8080))
    auth = source.options.get("auth", False)
    username = source.options.get("username", "soundagent")
    import os as _os
    password = _os.environ.get("SOUNDAGENT_WEBDAV_PASSWORD", "soundagent")

    inbox = cfg.library_root / "_inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    try:
        from wsgidav.wsgidav_app import WsgiDAVApp
        from wsgiref.simple_server import make_server
    except ImportError:
        log.error("wsgidav not installed — run: pip install wsgidav")
        return

    dav_config: dict = {
        "provider_mapping": {"/": str(inbox)},
        "verbose": 0,
        "logging": {"enable_loggers": []},
        "http_authenticator": {},
    }
    if auth:
        dav_config["http_authenticator"] = {
            "domain_controller": "wsgidav.dc.simple_dc.SimpleDomainController",
        }
        dav_config["simple_dc"] = {
            "user_mapping": {"*": {username: {"password": password}}}
        }

    app = WsgiDAVApp(dav_config)
    httpd = make_server("0.0.0.0", port, app)
    log.info(f"WebDAV serving {inbox} on port {port}")
    httpd.serve_forever()
