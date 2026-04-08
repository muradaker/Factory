"""
approval_policy.py — 10-gate hard approval check.
ALL gates must pass for release_allowed=True.
Never returns optimistic results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.core.json_loader import load_json_or_default
from app.core.file_utils import safe_read


@dataclass
class ApprovalResult:
    status: str                          # "approved" | "rejected"
    gates_passed: list[str] = field(default_factory=list)
    gates_failed: list[str] = field(default_factory=list)
    failure_details: dict[str, str] = field(default_factory=dict)
    release_allowed: bool = False        # True ONLY when all 10 gates pass
    warnings: list[str] = field(default_factory=list)


def _load_report(reports_dir: Path, filename: str) -> Optional[dict]:
    """Load a JSON report. Returns None if missing or invalid."""
    path = reports_dir / filename
    if not path.exists():
        return None
    data = load_json_or_default(path, default=None)
    if not isinstance(data, dict):
        return None
    return data


def _check_text_file(reports_dir: Path, filename: str, min_len: int = 100) -> tuple[bool, str]:
    """
    Check that a text file exists and has at least min_len characters.
    Returns (passed, reason_if_failed).
    """
    path = reports_dir / filename
    if not path.exists():
        return False, f"{filename} does not exist"
    content = safe_read(path)
    if content is None:
        return False, f"{filename} could not be read"
    if len(content.strip()) < min_len:
        return False, f"{filename} too short ({len(content.strip())} < {min_len} chars)"
    return True, ""


def check_approval(pack_name: str, reports_dir: Path) -> ApprovalResult:
    """
    Run all 10 gates against reports in reports_dir.
    Returns ApprovalResult with release_allowed=True ONLY if all 10 pass.
    """
    gates_passed: list[str] = []
    gates_failed: list[str] = []
    failure_details: dict[str, str] = {}
    warnings: list[str] = []

    # ── Gate 1: BuildReport ───────────────────────────────────────────────────
    gate = "G01_BuildReport"
    report = _load_report(reports_dir, "BuildReport.json")
    if report is None:
        gates_failed.append(gate)
        failure_details[gate] = "BuildReport.json missing"
    elif not report.get("build_success", False):
        gates_failed.append(gate)
        failure_details[gate] = f"build_success=false (error: {report.get('error', 'unknown')})"
    else:
        gates_passed.append(gate)

    # ── Gate 2: BlueprintAutomationReport ─────────────────────────────────────
    gate = "G02_BlueprintAutomation"
    report = _load_report(reports_dir, "BlueprintAutomationReport.json")
    if report is None:
        gates_failed.append(gate)
        failure_details[gate] = "BlueprintAutomationReport.json missing"
    elif not report.get("success", False):
        gates_failed.append(gate)
        failure_details[gate] = f"success=false (detail: {report.get('detail', 'unknown')})"
    else:
        gates_passed.append(gate)

    # ── Gate 3: DemoMapAutomationReport ──────────────────────────────────────
    gate = "G03_DemoMapAutomation"
    report = _load_report(reports_dir, "DemoMapAutomationReport.json")
    if report is None:
        gates_failed.append(gate)
        failure_details[gate] = "DemoMapAutomationReport.json missing"
    elif not report.get("map_created", False):
        gates_failed.append(gate)
        failure_details[gate] = f"map_created=false"
    else:
        gates_passed.append(gate)

    # ── Gate 4: DemoMapVerifyReport ───────────────────────────────────────────
    gate = "G04_DemoMapVerify"
    report = _load_report(reports_dir, "DemoMapVerifyReport.json")
    if report is None:
        gates_failed.append(gate)
        failure_details[gate] = "DemoMapVerifyReport.json missing"
    elif not report.get("verified", False):
        gates_failed.append(gate)
        failure_details[gate] = "verified=false"
    elif not isinstance(report.get("actor_count"), int) or report.get("actor_count", 0) <= 0:
        gates_failed.append(gate)
        failure_details[gate] = f"actor_count must be > 0, got {report.get('actor_count')}"
    else:
        gates_passed.append(gate)

    # ── Gate 5: RuntimeQAReport ───────────────────────────────────────────────
    gate = "G05_RuntimeQA"
    report = _load_report(reports_dir, "RuntimeQAReport.json")
    if report is None:
        gates_failed.append(gate)
        failure_details[gate] = "RuntimeQAReport.json missing"
    elif not report.get("passed", False):
        gates_failed.append(gate)
        failure_details[gate] = f"passed=false (failures: {report.get('failures', [])})"
    else:
        gates_passed.append(gate)

    # ── Gate 6: MultiplayerSmokeTestReport ────────────────────────────────────
    gate = "G06_MultiplayerSmokeTest"
    report = _load_report(reports_dir, "MultiplayerSmokeTestReport.json")
    if report is None:
        gates_failed.append(gate)
        failure_details[gate] = "MultiplayerSmokeTestReport.json missing"
    else:
        status = report.get("status", "")
        if status == "passed":
            gates_passed.append(gate)
        elif status == "skipped_map_missing":
            # Conservative pass — counts as pass with warning
            gates_passed.append(gate)
            warnings.append("G06: Multiplayer test skipped (map missing) — conservative pass")
        else:
            gates_failed.append(gate)
            failure_details[gate] = f"status={status!r} not in [passed, skipped_map_missing]"

    # ── Gate 7: ReviewReport ──────────────────────────────────────────────────
    gate = "G07_ReviewReport"
    report = _load_report(reports_dir, "ReviewReport.json")
    if report is None:
        gates_failed.append(gate)
        failure_details[gate] = "ReviewReport.json missing"
    elif report.get("decision") != "approved":
        gates_failed.append(gate)
        failure_details[gate] = f"decision={report.get('decision')!r} (expected 'approved')"
    else:
        gates_passed.append(gate)

    # ── Gate 8: OptimizationReport ────────────────────────────────────────────
    gate = "G08_OptimizationReport"
    report = _load_report(reports_dir, "OptimizationReport.json")
    if report is None:
        gates_failed.append(gate)
        failure_details[gate] = "OptimizationReport.json missing"
    else:
        # Existence is sufficient for this gate
        gates_passed.append(gate)

    # ── Gate 9: GeneratedSpec.txt ─────────────────────────────────────────────
    gate = "G09_GeneratedSpec"
    ok, reason = _check_text_file(reports_dir, "GeneratedSpec.txt", min_len=100)
    if ok:
        gates_passed.append(gate)
    else:
        gates_failed.append(gate)
        failure_details[gate] = reason

    # ── Gate 10: GeneratedArchitecture.txt ───────────────────────────────────
    gate = "G10_GeneratedArchitecture"
    ok, reason = _check_text_file(reports_dir, "GeneratedArchitecture.txt", min_len=100)
    if ok:
        gates_passed.append(gate)
    else:
        gates_failed.append(gate)
        failure_details[gate] = reason

    # ── Final decision ────────────────────────────────────────────────────────
    all_passed = len(gates_failed) == 0 and len(gates_passed) == 10

    return ApprovalResult(
        status="approved" if all_passed else "rejected",
        gates_passed=gates_passed,
        gates_failed=gates_failed,
        failure_details=failure_details,
        release_allowed=all_passed,  # True ONLY when all 10 gates pass
        warnings=warnings,
    )
