"""
progress_tracker.py — Writes LiveProgress.json, LiveEvents.jsonl, Heartbeat.json.
All writes are threadsafe. Heartbeat updates every 10 seconds via background thread.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import cfg
from app.core.json_loader import append_jsonl, save_json, load_json_or_default
from app.core.file_utils import safe_mkdir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProgressTracker:
    """
    One instance per pack. Manages progress files in workspace/{pack}/Reports/.
    Threadsafe for all public methods.
    """

    def __init__(self, pack_name: str):
        self.pack_name = pack_name
        self._reports_dir = cfg.reports_dir(pack_name)
        safe_mkdir(self._reports_dir)

        self._lock = threading.Lock()
        self._current_stage: Optional[str] = None
        self._stages_done: list[str] = []
        self._stages_failed: list[str] = []
        self._started_at: str = _now()

        # Heartbeat thread
        self._heartbeat_running = False
        self._heartbeat_thread: Optional[threading.Thread] = None

    # ── file paths ───────────────────────────────────────────────────────────

    @property
    def _live_progress_path(self) -> Path:
        return self._reports_dir / "LiveProgress.json"

    @property
    def _live_events_path(self) -> Path:
        return self._reports_dir / "LiveEvents.jsonl"

    @property
    def _heartbeat_path(self) -> Path:
        return self._reports_dir / "Heartbeat.json"

    # ── internal writes ──────────────────────────────────────────────────────

    def _write_progress(self) -> None:
        """Rewrite LiveProgress.json with current state. Must hold _lock."""
        data = {
            "pack": self.pack_name,
            "current_stage": self._current_stage,
            "stages_done": list(self._stages_done),
            "stages_failed": list(self._stages_failed),
            "started_at": self._started_at,
            "updated_at": _now(),
        }
        save_json(self._live_progress_path, data)

    def _write_heartbeat(self) -> None:
        """Write Heartbeat.json. Must hold _lock."""
        data = {
            "pack": self.pack_name,
            "alive": True,
            "ts": _now(),
            "current_stage": self._current_stage,
        }
        save_json(self._heartbeat_path, data)

    def _append_event(self, event: str, stage: str, detail: str = "") -> None:
        """Append one line to LiveEvents.jsonl. Must hold _lock."""
        record = {
            "event": event,
            "stage": stage,
            "pack": self.pack_name,
            "ts": _now(),
            "detail": detail,
        }
        append_jsonl(self._live_events_path, record)

    # ── heartbeat thread ─────────────────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
        """Background loop: write heartbeat every 10 seconds."""
        while self._heartbeat_running:
            try:
                with self._lock:
                    self._write_heartbeat()
            except Exception:
                pass  # Never crash the heartbeat thread
            time.sleep(10)

    def start_heartbeat(self) -> None:
        """Start the background heartbeat thread."""
        if self._heartbeat_running:
            return
        self._heartbeat_running = True
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name=f"heartbeat_{self.pack_name}"
        )
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        """Stop the heartbeat thread and write final dead heartbeat."""
        self._heartbeat_running = False
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=15)
        # Write final heartbeat with alive=False
        data = {
            "pack": self.pack_name,
            "alive": False,
            "ts": _now(),
            "current_stage": self._current_stage,
        }
        try:
            save_json(self._heartbeat_path, data)
        except Exception:
            pass

    # ── public API ────────────────────────────────────────────────────────────

    def stage_start(self, stage: str, detail: str = "") -> None:
        """Record that a stage has started."""
        with self._lock:
            self._current_stage = stage
            self._append_event("stage_start", stage, detail)
            self._write_progress()

    def stage_done(self, stage: str, detail: str = "") -> None:
        """Record successful completion of a stage."""
        with self._lock:
            if stage not in self._stages_done:
                self._stages_done.append(stage)
            # If it was previously failed, remove from failed list
            self._stages_failed = [s for s in self._stages_failed if s != stage]
            self._append_event("stage_done", stage, detail)
            self._write_progress()

    def stage_failed(self, stage: str, detail: str = "") -> None:
        """Record a stage failure."""
        with self._lock:
            if stage not in self._stages_failed:
                self._stages_failed.append(stage)
            self._append_event("stage_failed", stage, detail)
            self._write_progress()

    def log_event(self, event: str, stage: str, detail: str = "") -> None:
        """Log a generic event without changing stage state."""
        with self._lock:
            self._append_event(event, stage, detail)

    def get_summary(self) -> dict:
        """Return a snapshot of current progress state."""
        with self._lock:
            return {
                "pack": self.pack_name,
                "current_stage": self._current_stage,
                "stages_done": list(self._stages_done),
                "stages_failed": list(self._stages_failed),
                "started_at": self._started_at,
            }


# ── module-level tracker registry ────────────────────────────────────────────

_trackers: dict[str, ProgressTracker] = {}
_registry_lock = threading.Lock()


def get_tracker(pack_name: str) -> ProgressTracker:
    """Get or create a ProgressTracker for a pack."""
    with _registry_lock:
        if pack_name not in _trackers:
            _trackers[pack_name] = ProgressTracker(pack_name)
        return _trackers[pack_name]


def remove_tracker(pack_name: str) -> None:
    """Stop and remove tracker for a pack."""
    with _registry_lock:
        tracker = _trackers.pop(pack_name, None)
        if tracker:
            tracker.stop_heartbeat()
