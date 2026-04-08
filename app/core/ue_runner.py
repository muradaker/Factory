"""
ue_runner.py — Subprocess wrapper for UnrealEditor-Cmd and RunUAT.
NEVER trusts returncode alone. Also scans stdout for error markers.
If BUILD_WITH_UNREAL=false, returns a clearly-marked SKIPPED_BUILD result.
"""

import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import cfg
from app.core.file_utils import safe_mkdir

# Markers that indicate failure even if returncode == 0
_ERROR_MARKERS = [
    "Error:",
    "error:",
    "FAILED",
    "BUILD FAILED",
    "Fatal error",
    "Unhandled Exception",
    "Access violation",
]

# This marker means success even when other noise is present
_SUCCESS_MARKERS = [
    "0 error(s)",
    "BUILD SUCCESSFUL",
    "Automation completed successfully",
    "Plugin built successfully",
]


@dataclass
class UEResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int
    skipped: bool = False          # True when BUILD_WITH_UNREAL=false
    skip_reason: str = ""          # Populated if skipped
    error_markers_found: list[str] = field(default_factory=list)
    log_file: Optional[Path] = None


def _write_raw_log(stdout: str, stderr: str) -> Path:
    """Dump raw UE output to logs/ue_raw_{ts}.log."""
    log_dir = cfg.log_path()
    safe_mkdir(log_dir)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    log_file = log_dir / f"ue_raw_{ts}.log"
    combined = f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}\n"
    log_file.write_text(combined, encoding="utf-8", errors="replace")
    return log_file


def _scan_for_errors(text: str) -> list[str]:
    """Return list of error markers found in text."""
    found = []
    for marker in _ERROR_MARKERS:
        if marker in text:
            found.append(marker)
    return found


def _has_success_marker(text: str) -> bool:
    """Return True if any known success marker appears in text."""
    for marker in _SUCCESS_MARKERS:
        if marker in text:
            return True
    return False


def _interpret_result(returncode: int, stdout: str, stderr: str) -> tuple[bool, list[str]]:
    """
    Determine real success from returncode + content scanning.
    Returns (success: bool, error_markers: list).
    """
    combined = stdout + "\n" + stderr
    error_markers = _scan_for_errors(combined)

    if returncode != 0:
        # Non-zero is always failure
        return False, error_markers

    if error_markers:
        # Zero returncode but explicit error markers found → failure
        return False, error_markers

    # No error markers found — trust returncode 0
    return True, []


def _skipped_result(reason: str) -> UEResult:
    """Return a clearly-marked skip result. NOT a fake success."""
    return UEResult(
        success=False,
        stdout="",
        stderr="",
        returncode=-1,
        skipped=True,
        skip_reason=f"SKIPPED_BUILD: {reason}",
    )


def run_uat(args: list[str], timeout: int = 600) -> UEResult:
    """
    Run RunUAT.bat with given args.
    Returns UEResult with real success/failure determination.
    """
    if not cfg.build_with_unreal:
        return _skipped_result("BUILD_WITH_UNREAL=false")

    uat_path = cfg.unreal_run_uat
    if not Path(uat_path).exists():
        return UEResult(
            success=False,
            stdout="",
            stderr=f"RunUAT.bat not found: {uat_path}",
            returncode=-1,
        )

    cmd = [uat_path] + args
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            # Windows: don't open extra console windows
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as e:
        log_file = _write_raw_log(e.stdout or "", e.stderr or "")
        return UEResult(
            success=False,
            stdout=e.stdout or "",
            stderr=f"TIMEOUT after {timeout}s",
            returncode=-2,
            log_file=log_file,
        )
    except FileNotFoundError as e:
        return UEResult(
            success=False,
            stdout="",
            stderr=str(e),
            returncode=-1,
        )

    log_file = _write_raw_log(proc.stdout, proc.stderr)
    success, markers = _interpret_result(proc.returncode, proc.stdout, proc.stderr)

    return UEResult(
        success=success,
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
        error_markers_found=markers,
        log_file=log_file,
    )


def run_editor_cmd(
    project_path: str,
    exec_class: str,
    timeout: int = 300,
    extra_args: Optional[list[str]] = None,
) -> UEResult:
    """
    Run UnrealEditor-Cmd with -ExecClass and optional extra args.
    """
    if not cfg.build_with_unreal:
        return _skipped_result("BUILD_WITH_UNREAL=false")

    editor_path = cfg.ue_editor_cmd
    if not Path(editor_path).exists():
        return UEResult(
            success=False,
            stdout="",
            stderr=f"UnrealEditor-Cmd not found: {editor_path}",
            returncode=-1,
        )

    cmd = [
        editor_path,
        project_path,
        f"-ExecClass={exec_class}",
        "-Unattended",
        "-NullRHI",
        "-NoSplash",
        "-NoSound",
    ]
    if extra_args:
        cmd.extend(extra_args)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as e:
        log_file = _write_raw_log(e.stdout or "", e.stderr or "")
        return UEResult(
            success=False,
            stdout=e.stdout or "",
            stderr=f"TIMEOUT after {timeout}s",
            returncode=-2,
            log_file=log_file,
        )
    except FileNotFoundError as e:
        return UEResult(
            success=False,
            stdout="",
            stderr=str(e),
            returncode=-1,
        )

    log_file = _write_raw_log(proc.stdout, proc.stderr)
    success, markers = _interpret_result(proc.returncode, proc.stdout, proc.stderr)

    return UEResult(
        success=success,
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
        error_markers_found=markers,
        log_file=log_file,
    )


def run_build_plugin(plugin_dir: Path | str, ue_version: str = "5.5") -> UEResult:
    """
    Build a UE plugin using RunUAT BuildPlugin command.
    plugin_dir must contain the .uplugin file.
    """
    plugin_dir = Path(plugin_dir)

    if not cfg.build_with_unreal:
        return _skipped_result("BUILD_WITH_UNREAL=false")

    # Find .uplugin file
    uplugin_files = list(plugin_dir.glob("*.uplugin"))
    if not uplugin_files:
        return UEResult(
            success=False,
            stdout="",
            stderr=f"No .uplugin file found in {plugin_dir}",
            returncode=-1,
        )

    uplugin_path = uplugin_files[0]
    package_dir = plugin_dir / "Packaged"

    uat_args = [
        "BuildPlugin",
        f"-Plugin={uplugin_path}",
        f"-Package={package_dir}",
        f"-Rocket",
        f"-TargetPlatforms=Win64",
        "-CreateSubFolder",
    ]

    return run_uat(uat_args, timeout=cfg.model_timeout_seconds)
