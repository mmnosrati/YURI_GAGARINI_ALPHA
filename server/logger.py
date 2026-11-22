"""
Two-Day Rotating Logger Subsystem for Yuri Gagarin Search Engine.
Maintains rolling audit logs up to 48 hours for complete diagnostics and debugging.
"""

from __future__ import annotations

import logging
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import List

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)
SERVER_LOG_FILE = LOGS_DIR / "server.log"


def setup_rotating_logger() -> logging.Logger:
    """Configures root and yurigagarin loggers with 48-hour rotation."""
    logger = logging.getLogger("yurigagarin")
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers
    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 1. Console Stream Handler
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)

        # 2. 48-Hour Rotating File Handler (rotates daily, keeps 2 backups = 48h)
        try:
            rfh = TimedRotatingFileHandler(
                filename=str(SERVER_LOG_FILE),
                when="D",
                interval=1,
                backupCount=2,  # Retains logs for up to 2 days
                encoding="utf-8",
            )
            rfh.setFormatter(fmt)
            logger.addHandler(rfh)
        except Exception as e:
            print(f"Warning: Failed to setup rotating log file: {e}")

    return logger


def read_recent_logs(max_lines: int = 500) -> List[str]:
    """Reads the tail of server log files for debugging and admin panel viewing."""
    if not SERVER_LOG_FILE.exists():
        return ["[Log] No active log file found yet."]

    lines: List[str] = []
    # Collect current log file and up to 2 rotated days
    all_log_files = sorted(LOGS_DIR.glob("server.log*"), key=lambda f: f.stat().st_mtime)

    for lf in all_log_files:
        try:
            with open(lf, "r", encoding="utf-8", errors="replace") as f:
                lines.extend(f.readlines())
        except Exception:
            pass

    return [l.rstrip("\r\n") for l in lines[-max_lines:]]
