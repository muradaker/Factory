"""
approval_policy.py
Centralised gate checks used by ReleaseAgent.
Returns a structured result with per-gate pass/fail details.
"""

import json
from pathlib import Path

from app.core import config, logger as log


# Each gate: (gate_name, report_filename, condition_fn)
# condition_fn(report_dict) -> True means gate PASSES
GATES = [
    (
        "build_success",
        "BuildReport.json",
        lambda d: d.get("build_success") is True or d.get("skipped") is True,
    ),
    (
        "demo_map_verified",
        "DemoMapVerifyReport.json",
        lambda d: d.get("verified") is True,
    ),
    (
        "runtime_qa_passed",
        "RuntimeQAReport.json",
        lambda d: d.get("passed") is True or d.get("skipped") is True,
    ),
    (
        "review_approved",
        "ReviewReport.json",
        lambda d: d.get("decision") == "approved",
    ),
]


def check_approval(pack_name: str, reports_dir: Path) -> dict:
    """
    Run all approval gates and return a structured result dict.

    Returns:
        {
            "approved": bool,
            "gates_passed": [gate_name, ...],
            "gates_failed": [gate_name, ...],
        }
    """
    gates_passed = []
    gates_failed = []

    for gate_name, report_filename, condition_fn in GATES:
        report_path = Path(reports_dir) / report_filename
        if not report_path.exists():
            log.warning(f"[approval_policy] Gate '{gate_name}': report missing ({report_filename})")
            gates_failed.append(gate_name)
            continue

        try:
            data = json.loads(report_path.read_text())
        except Exception as exc:
            log.error(f"[approval_policy] Gate '{gate_name}': cannot parse {report_filename}: {exc}")
            gates_failed.append(gate_name)
            continue

        try:
            passes = condition_fn(data)
        except Exception as exc:
            log.error(f"[approval_policy] Gate '{gate_name}': condition evaluation error: {exc}")
            passes = False

        if passes:
            gates_passed.append(gate_name)
        else:
            gates_failed.append(gate_name)
            log.warning(f"[approval_policy] Gate FAILED: {gate_name} ({report_filename})")

    # Extra rule: if BUILD_WITH_UNREAL=false and ALLOW_BUILD_SKIP=false, reject
    if not config.BUILD_WITH_UNREAL and not config.ALLOW_BUILD_SKIP:
        if "build_skip_not_allowed" not in gates_failed:
            gates_failed.append("build_skip_not_allowed")
            log.warning("[approval_policy] build skip not allowed — adding blocking gate")

    approved = len(gates_failed) == 0
    return {
        "approved": approved,
        "gates_passed": gates_passed,
        "gates_failed": gates_failed,
    }
