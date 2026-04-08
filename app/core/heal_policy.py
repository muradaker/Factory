"""
heal_policy.py — SelfHeal rules: max passes, backoff, conditions.
Determines whether to attempt a heal pass and gathers failing report data.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from app.core.config import cfg
from app.core.json_loader import load_json_or_default
from app.core.state_store import get_state, mark_failed

# Report files that are checked for failure indicators
_REPORT_FILES = {
    "BuildReport.json": lambda d: not d.get("build_success", False),
    "BlueprintAutomationReport.json": lambda d: not d.get("success", False),
    "DemoMapAutomationReport.json": lambda d: not d.get("map_created", False),
    "DemoMapVerifyReport.json": lambda d: not d.get("verified", False),
    "RuntimeQAReport.json": lambda d: not d.get("passed", False),
    "MultiplayerSmokeTestReport.json": lambda d: d.get("status") not in ["passed", "skipped_map_missing"],
    "ReviewReport.json": lambda d: d.get("decision") != "approved",
    "OptimizationReport.json": lambda d: False,  # Existence check only
}


class HealPolicy:
    """
    Decides whether a heal pass should be attempted.
    Tracks heal attempts per pack in state.
    """

    def __init__(self):
        self._max_passes = cfg.self_heal_max_passes_per_run
        self._enabled = cfg.self_heal_enabled

    def should_heal(
        self,
        pack_name: str,
        pass_number: int,
        failed_stages: list[str],
    ) -> bool:
        """
        Return True if a heal pass is warranted.
        Conditions:
          - SELF_HEAL_ENABLED must be true
          - pass_number must be < max_passes
          - There must be at least one failed stage
          - No permanent-failure conditions (reserved for future use)
        """
        if not self._enabled:
            return False

        if not failed_stages:
            # Nothing to heal
            return False

        if pass_number >= self._max_passes:
            return False

        return True

    def get_failing_reports(self, reports_dir: Path) -> dict[str, dict]:
        """
        Scan reports_dir for all known report files.
        Return a dict of {report_filename: content_dict} for every report
        that either doesn't exist or has a failure indicator.
        """
        failing: dict[str, dict] = {}

        for report_name, is_failing_fn in _REPORT_FILES.items():
            report_path = reports_dir / report_name
            if not report_path.exists():
                failing[report_name] = {"error": "file_missing", "path": str(report_path)}
                continue

            content = load_json_or_default(report_path, default={})
            if not isinstance(content, dict):
                failing[report_name] = {"error": "invalid_json", "path": str(report_path)}
                continue

            if is_failing_fn(content):
                failing[report_name] = content

        return failing

    def get_heal_context(self, pack_name: str, reports_dir: Path) -> dict:
        """
        Build a full heal context dict with state info + failing report data.
        Passed to the heal agent.
        """
        state = get_state(pack_name)
        failing_reports = self.get_failing_reports(reports_dir)

        return {
            "pack_name": pack_name,
            "failed_stages": state.get("stages_failed", []),
            "failure_reasons": state.get("failure_reasons", {}),
            "run_count": state.get("run_count", 0),
            "failing_reports": failing_reports,
        }

    def record_heal_attempt(self, pack_name: str, pass_number: int, stages: list[str]) -> None:
        """Log that a heal pass was attempted (stored in state as metadata)."""
        # Mark each failed stage with a heal-attempt note in state
        for stage in stages:
            mark_failed(
                pack_name,
                stage,
                f"Heal attempted pass {pass_number} — awaiting retry",
            )

    def compute_backoff(self, pass_number: int) -> float:
        """
        Compute seconds to wait before next heal attempt.
        Exponential backoff: 5s, 15s, 45s, ...
        """
        return 5.0 * (3 ** pass_number)
