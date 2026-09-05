from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "office_reminder.log"

    # Root logger for app
    logger = logging.getLogger("office_reminder")
    logger.setLevel(level)
    logger.propagate = False

    # Avoid duplicate handlers on re-init
    if logger.handlers:
        return logger

    # File handler with rotation (5 MB per file, 3 backups)
    fh = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(fh)

    # Console handler for dev (only if not frozen)
    try:
        if not getattr(sys, "frozen", False):
            ch = logging.StreamHandler(sys.stdout)
            ch.setLevel(logging.WARNING)
            ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
            logger.addHandler(ch)
    except Exception:
        pass

    # Uncaught exception logging
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception

    logger.info("Logging initialized at %s", log_file)
    return logger


def get_logger(name: str = "office_reminder") -> logging.Logger:
    return logging.getLogger(name)
