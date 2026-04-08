"""
release.py — ReleaseAgent
Packages the final plugin .zip ONLY when approval passes all gates.
Writes PipelineSummary.json with full gate results.
"""

import json
import zipfile
import time
from pathlib import Path

from app.core import config, logger as log
from app.flows import approval_policy


class ReleaseAgent:
    def __init__(self):
        self.name = "ReleaseAgent"

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    def run(self, pack_name: str) -> dict:
        workspace = Path(config.WORKSPACE_ROOT) / pack_name
        reports_dir = workspace / "Reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        release_dir = Path(config.RELEASE_DIR)
        release_dir.mkdir(parents=True, exist_ok=True)

        report_path = reports_dir / "PipelineSummary.json"

        log.info(f"[{self.name}] Checking approval for '{pack_name}'")

        # ---- 1. Run approval gate checks ----
        approval_result = approval_policy.check_approval(pack_name, reports_dir)
        approved = approval_result["approved"]
        gates_passed = approval_result.get("gates_passed", [])
        gates_failed = approval_result.get("gates_failed", [])

        # ---- 2. Block release if any gate failed ----
        if not approved:
            report = {
                "pack_name": pack_name,
                "approved": False,
                "release_blocked": True,
                "release_path": None,
                "gates_passed": gates_passed,
                "gates_failed": gates_failed,
                "approval_status": "rejected",
                "release_allowed": False,
                "reason": f"gates_failed: {gates_failed}",
            }
            report_path.write_text(json.dumps(report, indent=2))
            log.warning(f"[{self.name}] Release BLOCKED — gates failed: {gates_failed}")
            return {"zip_path": None, "approved": False, "report_path": str(report_path)}

        # ---- 3. Approved — package the plugin ----
        zip_filename = f"{pack_name}_UE55.zip"
        zip_path = release_dir / zip_filename
        plugin_source = workspace / "PluginSource"

        try:
            self._create_zip(plugin_source, zip_path, pack_name)
            log.info(f"[{self.name}] Created release zip: {zip_path}")
        except Exception as exc:
            log.error(f"[{self.name}] Zip creation failed: {exc}")
            report = {
                "pack_name": pack_name,
                "approved": True,
                "release_blocked": True,
                "release_path": None,
                "gates_passed": gates_passed,
                "gates_failed": gates_failed,
                "approval_status": "approved",
                "release_allowed": False,
                "reason": f"zip_creation_failed: {exc}",
            }
            report_path.write_text(json.dumps(report, indent=2))
            return {"zip_path": None, "approved": True, "report_path": str(report_path)}

        report = {
            "pack_name": pack_name,
            "approved": True,
            "release_blocked": False,
            "release_path": str(zip_path),
            "gates_passed": gates_passed,
            "gates_failed": gates_failed,
            "approval_status": "approved",
            "release_allowed": True,
            "reason": None,
        }
        report_path.write_text(json.dumps(report, indent=2))
        return {"zip_path": str(zip_path), "approved": True, "report_path": str(report_path)}

    # ------------------------------------------------------------------ #
    # Build the release zip from PluginSource
    # ------------------------------------------------------------------ #
    def _create_zip(self, plugin_source: Path, zip_path: Path, pack_name: str) -> None:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if not plugin_source.exists():
                raise FileNotFoundError(f"PluginSource directory not found: {plugin_source}")

            file_count = 0
            for file in sorted(plugin_source.rglob("*")):
                if file.is_file():
                    # Archive path inside zip: PackName/PluginSource/relative_path
                    arcname = Path(pack_name) / "PluginSource" / file.relative_to(plugin_source)
                    zf.write(file, arcname)
                    file_count += 1

            log.info(f"[{self.name}] Zipped {file_count} files from {plugin_source}")
