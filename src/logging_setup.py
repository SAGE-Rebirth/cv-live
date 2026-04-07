"""Shared logging configuration.

Child processes spawned with the 'spawn' start method do NOT inherit the
parent's logging configuration. Each process must call setup_logging() at
the top of its run() method, otherwise log records vanish silently.
"""

import logging
import os

from src.config import Config


def setup_logging(component: str) -> None:
    """Configure root logging for a process. Idempotent."""
    root = logging.getLogger()
    if getattr(root, "_cv_live_configured", False):
        return

    os.makedirs(Config.LOGS_DIR, exist_ok=True)
    log_file = os.path.join(Config.LOGS_DIR, "app.log")

    handlers = [
        logging.StreamHandler(),
        logging.FileHandler(log_file),
    ]
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
        format=f"%(asctime)s - [{component}] - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )
    root._cv_live_configured = True
