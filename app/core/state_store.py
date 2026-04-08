"""
state_store.py — Per-pack run state: stage tracking, status, run count.
Persisted to state/{pack_name}.state.json.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import cfg
from app.core.json_loader import load_json_or_default, save_json

_locks: dict[str, threading.Lock] = {}
_locks_meta = threading.Lock()


def _get_lock(pack_name: str) -> threading.Lock:
    """Return a per-pack threading lock."""
    with _locks_meta:
        if pack_name not in _locks:
            _locks[pack_name] = threading.Lock()
        return _locks[pack_name]


def _state_path(pack_name: str) -> Path:
    return cfg.state_path() / f"{pack_name}.state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(pack_name: str) -> dict:
    """Load state dict from disk or return a fresh skeleton."""
    data = load_json_or_default(_state_path(pack_name), default=None)
    if data is None or not isinstance(data, dict):
        return {
            "pack_name": pack_name,
            "current_stage": None,
            "stages_done": [],
            "stages_failed": [],
            "failure_reasons": {},
            "run_count": 0,
            "last_updated": _now(),
        }
    return data


def _save(pack_name: str, state: dict) -> None:
    state["last_updated"] = _now()
    save_json(_state_path(pack_name), state)


# ── public API ───────────────────────────────────────────────────────────────


def mark_done(pack_name: str, stage: str) -> None:
    """Record a stage as successfully completed."""
    lock = _get_lock(pack_name)
    with lock:
        state = _load(pack_name)
        if stage not in state["stages_done"]:
            state["stages_done"].append(stage)
        # Remove from failed list if previously failed then healed
        state["stages_failed"] = [s for s in state["stages_failed"] if s != stage]
        state["current_stage"] = stage
        _save(pack_name, state)


def mark_failed(pack_name: str, stage: str, reason: str) -> None:
    """Record a stage failure with a reason."""
    lock = _get_lock(pack_name)
    with lock:
        state = _load(pack_name)
        if stage not in state["stages_failed"]:
            state["stages_failed"].append(stage)
        state["failure_reasons"][stage] = reason
        state["current_stage"] = stage
        _save(pack_name, state)


def set_current_stage(pack_name: str, stage: str) -> None:
    """Update the current active stage."""
    lock = _get_lock(pack_name)
    with lock:
        state = _load(pack_name)
        state["current_stage"] = stage
        _save(pack_name, state)


def is_done(pack_name: str, stage: str) -> bool:
    """Return True if stage has been successfully completed."""
    state = _load(pack_name)
    return stage in state.get("stages_done", [])


def increment_run_count(pack_name: str) -> int:
    """Increment run_count and return new value."""
    lock = _get_lock(pack_name)
    with lock:
        state = _load(pack_name)
        state["run_count"] = state.get("run_count", 0) + 1
        _save(pack_name, state)
        return state["run_count"]


def get_state(pack_name: str) -> dict:
    """Return full state dict (read-only snapshot)."""
    return _load(pack_name)


def reset(pack_name: str) -> None:
    """Wipe state for a pack (start fresh)."""
    lock = _get_lock(pack_name)
    with lock:
        fresh = {
            "pack_name": pack_name,
            "current_stage": None,
            "stages_done": [],
            "stages_failed": [],
            "failure_reasons": {},
            "run_count": 0,
            "last_updated": _now(),
        }
        _save(pack_name, fresh)


def get_failed_stages(pack_name: str) -> list[str]:
    """Return list of stages that are currently in failed state."""
    state = _load(pack_name)
    return state.get("stages_failed", [])


def get_failure_reason(pack_name: str, stage: str) -> Optional[str]:
    """Return failure reason for a stage, or None."""
    state = _load(pack_name)
    return state.get("failure_reasons", {}).get(stage)
