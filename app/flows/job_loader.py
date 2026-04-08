"""
job_loader.py
Loads and validates job definition files from input/jobs/{pack_name}.job.json.
"""

import json
from pathlib import Path


REQUIRED_TOP_LEVEL_KEYS = ["job_meta", "product_definition", "implementation_scope"]


def load_job(pack_name: str) -> dict:
    """
    Load job definition from input/jobs/{pack_name}.job.json.
    Validates required top-level fields.
    Raises FileNotFoundError or ValueError on invalid data.
    """
    job_path = Path("input") / "jobs" / f"{pack_name}.job.json"

    if not job_path.exists():
        raise FileNotFoundError(
            f"Job file not found: {job_path}\n"
            f"Make sure input/jobs/{pack_name}.job.json exists."
        )

    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in job file {job_path}: {e}")

    # Validate required top-level keys
    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in job]
    if missing:
        raise ValueError(
            f"Job file {job_path} is missing required keys: {missing}\n"
            f"Required: {REQUIRED_TOP_LEVEL_KEYS}"
        )

    # Validate nested required fields
    meta = job.get("job_meta", {})
    if not meta.get("pack_name"):
        raise ValueError(f"job_meta.pack_name is required in {job_path}")

    if not job.get("product_definition", {}).get("title"):
        raise ValueError(f"product_definition.title is required in {job_path}")

    if not job.get("implementation_scope", {}).get("core_features"):
        raise ValueError(f"implementation_scope.core_features is required in {job_path}")

    return job
