"""
dataset_writer.py — Writes structured fine-tuning records to datasets/.
Each record is a self-contained JSON file with input/output/status.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.core.json_loader import save_json
from app.core.file_utils import safe_mkdir

# Root datasets directory
_DATASETS_ROOT = Path(__file__).resolve().parents[2] / "datasets"

VALID_CATEGORIES = {
    "specs",
    "architectures",
    "code_generations",
    "build_failures",
    "fixes",
    "approvals",
    "rejections",
}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def _category_dir(category: str) -> Path:
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Unknown dataset category: {category!r}. Valid: {VALID_CATEGORIES}")
    return _DATASETS_ROOT / category


def write_record(
    category: str,
    pack_name: str,
    input_ctx: Any,
    expected_output: Any,
    actual_output: Any,
    status: str,
    failure_reason: Optional[str] = None,
) -> Path:
    """
    Write a single fine-tuning record to datasets/{category}/{pack_name}_{ts}.json.

    Args:
        category:        One of VALID_CATEGORIES.
        pack_name:       Plugin pack identifier.
        input_ctx:       The input context given to the model (prompt, state, etc.).
        expected_output: What the ideal output should have been.
        actual_output:   What the model/pipeline actually produced.
        status:          "success" | "failure" | "partial" | "skipped".
        failure_reason:  Optional explanation if status == "failure".

    Returns:
        Path to the written JSON file.
    """
    cat_dir = _category_dir(category)
    safe_mkdir(cat_dir)

    record = {
        "schema_version": "1.0",
        "category": category,
        "pack_name": pack_name,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "input": input_ctx,
        "expected_output": expected_output,
        "actual_output": actual_output,
        "failure_reason": failure_reason,
    }

    filename = f"{pack_name}_{_ts()}.json"
    out_path = cat_dir / filename
    save_json(out_path, record)
    return out_path


def write_build_failure(
    pack_name: str,
    build_log: str,
    error_summary: str,
    fix_attempted: Optional[str] = None,
) -> Path:
    """Convenience wrapper for build failure records."""
    return write_record(
        category="build_failures",
        pack_name=pack_name,
        input_ctx={"build_log_excerpt": build_log[:2000]},
        expected_output={"build_success": True},
        actual_output={"build_success": False, "error_summary": error_summary},
        status="failure",
        failure_reason=error_summary,
    )


def write_approval_record(
    pack_name: str,
    gates_passed: list[str],
    gates_failed: list[str],
    approved: bool,
) -> Path:
    """Convenience wrapper for approval/rejection records."""
    category = "approvals" if approved else "rejections"
    return write_record(
        category=category,
        pack_name=pack_name,
        input_ctx={"gates_checked": gates_passed + gates_failed},
        expected_output={"all_gates_pass": True},
        actual_output={
            "gates_passed": gates_passed,
            "gates_failed": gates_failed,
            "approved": approved,
        },
        status="success" if approved else "failure",
        failure_reason=f"Failed gates: {gates_failed}" if gates_failed else None,
    )


def count_records(category: str) -> int:
    """Return number of records written to a category."""
    cat_dir = _category_dir(category)
    if not cat_dir.exists():
        return 0
    return len(list(cat_dir.glob("*.json")))
