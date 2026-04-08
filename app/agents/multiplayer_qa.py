"""
multiplayer_qa.py — MultiplayerQAAgent
Launches server + client smoke test, verifies both survive the timeout.
Writes MultiplayerSmokeTestReport.json. Never claims pass without real evidence.
"""

import json
import os
import subprocess
import time
from pathlib import Path

from app.core import config, logger as log


class MultiplayerQAAgent:
    def __init__(self):
        self.name = "MultiplayerQAAgent"

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    def run(self, pack_name: str) -> dict:
        workspace = Path(config.WORKSPACE_ROOT) / pack_name
        reports_dir = workspace / "Reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / "MultiplayerSmokeTestReport.json"

        log.info(f"[{self.name}] Starting multiplayer smoke test for '{pack_name}'")

        # Guard: build must be enabled
        if not config.BUILD_WITH_UNREAL:
            return self._write_report(report_path, pack_name,
                                      status="skipped_build_disabled",
                                      server_launched=False, client_launched=False,
                                      server_survived=False, client_survived=False,
                                      duration=0.0, error="BUILD_WITH_UNREAL=false")

        # Guard: demo map verify report must exist and be verified
        verify_report_path = reports_dir / "DemoMapVerifyReport.json"
        if not verify_report_path.exists():
            log.warning(f"[{self.name}] DemoMapVerifyReport.json missing")
            return self._write_report(report_path, pack_name,
                                      status="skipped_map_missing",
                                      server_launched=False, client_launched=False,
                                      server_survived=False, client_survived=False,
                                      duration=0.0, error="DemoMapVerifyReport.json not found")

        try:
            verify_data = json.loads(verify_report_path.read_text())
        except Exception as exc:
            return self._write_report(report_path, pack_name,
                                      status="skipped_map_missing",
                                      server_launched=False, client_launched=False,
                                      server_survived=False, client_survived=False,
                                      duration=0.0, error=f"Cannot parse verify report: {exc}")

        if not verify_data.get("verified", False):
            return self._write_report(report_path, pack_name,
                                      status="skipped_map_missing",
                                      server_launched=False, client_launched=False,
                                      server_survived=False, client_survived=False,
                                      duration=0.0, error="DemoMapVerifyReport verified==false")

        # Resolve demo map path from automation report
        auto_report_path = reports_dir / "DemoMapAutomationReport.json"
        map_path = self._resolve_map_path(pack_name, auto_report_path)

        # Resolve UE editor binary
        editor_cmd = config.UE_EDITOR_CMD          # e.g. "UnrealEditor-Cmd"
        project_path = config.UE_PROJECT_PATH      # full .uproject path

        server_proc = None
        client_proc = None
        server_launched = False
        client_launched = False
        server_survived = False
        client_survived = False
        error_msg = None

        start = time.time()

        try:
            # Launch dedicated server
            server_args = [
                editor_cmd, project_path,
                f"{map_path}?listen",
                "-server", "-log", "-nosplash",
            ]
            log.info(f"[{self.name}] Launching server: {' '.join(server_args)}")
            server_proc = subprocess.Popen(server_args,
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
            server_launched = True

            # Wait for server to initialise before launching client
            time.sleep(15)

            # Launch game client
            client_args = [
                editor_cmd, project_path,
                map_path,
                "-game", "-log", "-nosplash",
            ]
            log.info(f"[{self.name}] Launching client: {' '.join(client_args)}")
            client_proc = subprocess.Popen(client_args,
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
            client_launched = True

            # Wait for the configured smoke-test duration
            timeout = int(getattr(config, "MULTIPLAYER_TEST_TIMEOUT_SECONDS", 30))
            time.sleep(timeout)

            # Check survival — poll() returns None if still running
            server_survived = (server_proc.poll() is None)
            client_survived = (client_proc.poll() is None)

        except Exception as exc:
            error_msg = str(exc)
            log.error(f"[{self.name}] Exception during smoke test: {exc}")

        finally:
            # Always terminate both processes regardless of outcome
            for proc, label in [(server_proc, "server"), (client_proc, "client")]:
                if proc is not None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=10)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    log.info(f"[{self.name}] {label} process terminated")

        duration = round(time.time() - start, 2)

        # Determine final status — must have real evidence
        if server_launched and client_launched and server_survived and client_survived:
            status = "passed"
        else:
            status = "failed"

        return self._write_report(report_path, pack_name,
                                  status=status,
                                  server_launched=server_launched,
                                  client_launched=client_launched,
                                  server_survived=server_survived,
                                  client_survived=client_survived,
                                  duration=duration, error=error_msg)

    # ------------------------------------------------------------------ #
    # Resolve demo map path from automation report (fallback to default)
    # ------------------------------------------------------------------ #
    def _resolve_map_path(self, pack_name: str, auto_report_path: Path) -> str:
        # Try to read the map path recorded by a previous pipeline stage
        if auto_report_path.exists():
            try:
                data = json.loads(auto_report_path.read_text())
                if data.get("map_path"):
                    return data["map_path"]
            except Exception:
                pass
        # Fallback to content-browser path convention
        return f"/Game/{pack_name}/Maps/DemoMap"

    # ------------------------------------------------------------------ #
    # Write report and return standard dict
    # ------------------------------------------------------------------ #
    def _write_report(
        self, report_path: Path, pack_name: str,
        status: str,
        server_launched: bool, client_launched: bool,
        server_survived: bool, client_survived: bool,
        duration: float, error,
    ) -> dict:
        report = {
            "pack_name": pack_name,
            "status": status,
            "server_launched": server_launched,
            "client_launched": client_launched,
            "server_survived": server_survived,
            "client_survived": client_survived,
            "test_duration_s": duration,
            "error": error,
        }
        report_path.write_text(json.dumps(report, indent=2))
        log.info(f"[{self.name}] Smoke test status={status}")
        return {"report_path": str(report_path), "status": status}
