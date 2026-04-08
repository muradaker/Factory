"""
logger.py — Colored rich terminal logger + plain-text file logger.
Colors: stage_start=cyan, stage_success=green, stage_fail=red,
        info=white, warn=yellow.
"""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.text import Text

from app.core.config import cfg

# Single rich console (stderr=False → stdout)
_console = Console(highlight=False)

# File handlers cache: pack_name → logging.Logger
_file_loggers: dict[str, logging.Logger] = {}


def _get_file_logger(pack_name: str) -> logging.Logger:
    """Return (or create) a file-based logger for a pack."""
    if pack_name in _file_loggers:
        return _file_loggers[pack_name]

    log_dir = Path(cfg.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{pack_name}_{ts}.log"

    logger = logging.getLogger(f"myth.{pack_name}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # don't bubble to root

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
    )
    logger.addHandler(fh)

    _file_loggers[pack_name] = logger
    return logger


def _ts() -> str:
    return datetime.utcnow().strftime("%H:%M:%S")


# ── public API ──────────────────────────────────────────────────────────────


def log_stage_start(pack: str, stage: str) -> None:
    """Log the start of a pipeline stage (cyan)."""
    msg = f"[{_ts()}] ▶ {pack} / {stage}"
    text = Text(msg, style="bold cyan")
    _console.print(text)
    _get_file_logger(pack).info(f"STAGE_START | {stage}")


def log_stage_done(pack: str, stage: str, duration_s: float) -> None:
    """Log successful completion of a stage (green)."""
    msg = f"[{_ts()}] ✔ {pack} / {stage}  ({duration_s:.1f}s)"
    text = Text(msg, style="bold green")
    _console.print(text)
    _get_file_logger(pack).info(f"STAGE_DONE  | {stage} | {duration_s:.1f}s")


def log_stage_fail(pack: str, stage: str, reason: str) -> None:
    """Log a stage failure (red)."""
    msg = f"[{_ts()}] ✘ {pack} / {stage}  — {reason}"
    text = Text(msg, style="bold red")
    _console.print(text)
    _get_file_logger(pack).error(f"STAGE_FAIL  | {stage} | {reason}")


def log_info(pack: str, message: str) -> None:
    """General info log (white)."""
    msg = f"[{_ts()}]   {pack} : {message}"
    text = Text(msg, style="white")
    _console.print(text)
    _get_file_logger(pack).info(message)


def log_warn(pack: str, message: str) -> None:
    """Warning log (yellow)."""
    msg = f"[{_ts()}] ⚠ {pack} : {message}"
    text = Text(msg, style="bold yellow")
    _console.print(text)
    _get_file_logger(pack).warning(message)


def log_system(message: str) -> None:
    """System-level (no pack) message (dim white)."""
    msg = f"[{_ts()}] SYS: {message}"
    _console.print(Text(msg, style="dim white"))
    logging.getLogger("myth.system").info(message)
