"""
build_fix.py — BuildFixAgent
Runs UE BuildPlugin, parses output, writes BuildReport.json.
"""

import json
import os
import time
from pathlib import Path

from app.core import ue_runner, config, logger as log


class BuildFixAgent:
    def __init__(self):
        self.name = "BuildFixAgent"

    def run(self, pack_name: str) -> dict:
        # Resolve paths
        workspace = Path(config.WORKSPACE_ROOT) / pack_name
        reports_dir = workspace / "Reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / "BuildReport.json"
        plugin_dir = workspace / "PluginSource"

        log.info(f"[{self.name}] Starting build for '{pack_name}'")

        # If build is disabled via env flag, skip with explicit false result
        if not config.BUILD_WITH_UNREAL:
            report = {
                "pack_name": pack_name,
                "build_success": False,
                "skipped": True,
                "reason": "BUILD_WITH_UNREAL=false",
                "returncode": None,
                "error_lines": [],
                "warning_lines": [],
                "stdout_excerpt": "",
                "duration_s": 0.0,
            }
            report_path.write_text(json.dumps(report, indent=2))
            log.info(f"[{self.name}] Build skipped (BUILD_WITH_UNREAL=false)")
            return {"report_path": str(report_path), "build_success": False, "status": "failed"}

        # Run the actual Unreal build
        start = time.time()
        result = ue_runner.run_build_plugin(plugin_dir=str(plugin_dir))
        duration = round(time.time() - start, 2)

        stdout = result.stdout or ""
        returncode = result.returncode

        # Parse stdout for error and warning lines
        error_lines = []
        warning_lines = []
        for line in stdout.splitlines():
            if "error C" in line or "error LNK" in line or ("FAILED" in line and "error" in line.lower()):
                error_lines.append(line.strip())
            elif "warning C" in line or "warning:" in line.lower():
                warning_lines.append(line.strip())

        # Determine build success strictly — no faking
        success_signals = ("Build successful" in stdout) or ("0 error(s)" in stdout)
        build_success = success_signals and (returncode == 0)

        # Truncate stdout to a reasonable excerpt for the report
        lines = stdout.splitlines()
        excerpt_lines = lines[-80:] if len(lines) > 80 else lines
        stdout_excerpt = "\n".join(excerpt_lines)

        report = {
            "pack_name": pack_name,
            "build_success": build_success,
            "skipped": False,
            "reason": None,
            "returncode": returncode,
            "error_lines": error_lines[:50],       # cap at 50 lines
            "warning_lines": warning_lines[:50],
            "stdout_excerpt": stdout_excerpt,
            "duration_s": duration,
        }
        report_path.write_text(json.dumps(report, indent=2))

        status = "done" if build_success else "failed"
        log.info(f"[{self.name}] Build finished — success={build_success}, status={status}")
        return {"report_path": str(report_path), "build_success": build_success, "status": status}
