import logging
import logging.handlers

from soundagent.config import Config

FMT = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")


class _SafeStreamHandler(logging.StreamHandler):
    """StreamHandler that survives narrow console encodings (e.g. Windows cp1252)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            try:
                self.stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                safe = msg.encode("ascii", "backslashreplace").decode("ascii")
                self.stream.write(safe + self.terminator)
            self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


def setup_logging(cfg: Config) -> logging.Logger:
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    ch = _SafeStreamHandler()
    ch.setFormatter(FMT)
    root.addHandler(ch)

    # file handler only if library root exists (created by `init`)
    log_path = cfg.library_root / "soundagent.log"
    if cfg.library_root.exists():
        fh = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setFormatter(FMT)
        root.addHandler(fh)

    return logging.getLogger("soundagent")
