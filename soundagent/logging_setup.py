import logging
import logging.handlers

from soundagent.config import Config

FMT = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")


def setup_logging(cfg: Config) -> logging.Logger:
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    ch = logging.StreamHandler()
    ch.setFormatter(FMT)
    root.addHandler(ch)

    # file handler only if library root exists (created by `init`)
    log_path = cfg.library_root / "soundagent.log"
    if cfg.library_root.exists():
        fh = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=5 * 1024 * 1024, backupCount=5
        )
        fh.setFormatter(FMT)
        root.addHandler(fh)

    return logging.getLogger("soundagent")
