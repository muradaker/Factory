"""
self_heal.py — SelfHealAgent
Collects failures, retrieves past patches from memory, asks LLM to produce
a patch bundle, validates it strictly, applies valid patches, and signals
the pipeline to retry failed stages.
"""

import json
import re
import os
from pathlib import Path

from app.core import config, logger as log, llm_client, memory


class SelfHealAgent:
    def __init__(self):
        self.name = "SelfHealAgent"

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    def run(self, pack_name: str, pass_number: int = 1, failed_stages: list = None) -> dict:
        workspace = Path(config.WORKSPACE_ROOT) / pack_name
        reports_dir = workspace / "Reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / "SelfHealReport.json"

        failed_stages = failed_stages or []
        log.info(f"[{self.name}] Pass #{pass_number} for '{pack_name}', failed_stages={failed_stages}")

        # ---- 1. Collect all failed reports ----
        failed_reports = self.collect_failures(pack_name, reports_dir)

        # ---- 2. Retrieve past successful patches from memory ----
        query = f"{pack_name} {' '.join(failed_stages)}"
        past_patches = memory.retrieve(category="patches", query=query)

        # ---- 3. Ask LLM to produce a patch bundle ----
        patch_bundle_raw = self._request_patches(pack_name, failed_reports, past_patches, failed_stages)

        # ---- 4. Validate patch bundle JSON strictly ----
        valid, patches, parse_error = self._validate_patch_bundle(patch_bundle_raw, pack_name)

        if not valid:
            log.error(f"[{self.name}] Patch JSON invalid: {parse_error}")
            return self._write_report(
                report_path, pack_name,
                pass_number=pass_number,
                patches_attempted=0, patches_applied=0,
                success=False, failed_stages=failed_stages,
                reason=f"invalid_patch_json: {parse_error}",
            )

        # ---- 5. Apply valid patches ----
        patches_attempted = len(patches)
        patches_applied = self._apply_patches(patches, pack_name)

        success = patches_applied > 0

        # ---- 6. Store this patch attempt in memory for future runs ----
        if success:
            memory.write(
                category="patches",
                key=f"{pack_name}_pass{pass_number}",
                value=json.dumps({
                    "pack_name": pack_name,
                    "pass_number": pass_number,
                    "failed_stages": failed_stages,
                    "patches": patches,
                }),
            )

        return self._write_report(
            report_path, pack_name,
            pass_number=pass_number,
            patches_attempted=patches_attempted,
            patches_applied=patches_applied,
            success=success,
            failed_stages=failed_stages,
            reason=None,
        )

    # ------------------------------------------------------------------ #
    # Collect all failed reports from the Reports directory
    # ------------------------------------------------------------------ #
    def collect_failures(self, pack_name: str, reports_dir: Path) -> dict:
        """Return {report_filename: parsed_content} for every failed report."""
        failures = {}
        if not reports_dir.exists():
            return failures

        for report_file in sorted(reports_dir.glob("*.json")):
            try:
                data = json.loads(report_file.read_text())
            except Exception:
                continue

            # Detect failure across different report schemas
            is_failed = (
                data.get("build_success") is False
                or data.get("passed") is False
                or data.get("status") in ("failed",)
                or data.get("decision") == "rejected"
                or data.get("approved") is False
                or data.get("grade") in ("C", "D")
            )
            if is_failed:
                failures[report_file.name] = data

        return failures

    # ------------------------------------------------------------------ #
    # Build the LLM prompt and request a patch bundle
    # ------------------------------------------------------------------ #
    def _request_patches(self, pack_name: str, failed_reports: dict,
                         past_patches: list, failed_stages: list) -> str:
        reports_section = json.dumps(failed_reports, indent=2)[:4000]
        past_section = json.dumps(past_patches, indent=2)[:2000]

        prompt = (
            f"You are an autonomous repair agent for a production Unreal Engine 5 plugin system.\n"
            f"Plugin: {pack_name}\n"
            f"Failed stages: {failed_stages}\n\n"
            f"=== Failed QA Reports ===\n{reports_section}\n\n"
            f"=== Previously Applied Patches (for reference) ===\n{past_section}\n\n"
            "Produce a patch bundle to fix the failures. "
            "Return ONLY valid JSON in this exact format — no markdown, no explanation:\n"
            '{"patches": [{"file": "relative/path", "action": "overwrite"|"append"|"insert_after", '
            '"target_line": "<string or null>", "content": "<new content>"}]}'
        )
        try:
            return llm_client.complete(prompt, max_tokens=2048)
        except Exception as exc:
            log.error(f"[{self.name}] LLM request failed: {exc}")
            return ""

    # ------------------------------------------------------------------ #
    # Validate patch bundle — strict JSON parse + path safety checks
    # ------------------------------------------------------------------ #
    def _validate_patch_bundle(self, raw: str, pack_name: str):
        if not raw.strip():
            return False, [], "empty LLM response"

        # Strip markdown fences if the LLM wrapped the output
        clean = re.sub(r"```[a-z]*", "", raw).strip().strip("`").strip()

        try:
            bundle = json.loads(clean)
        except json.JSONDecodeError as exc:
            return False, [], str(exc)

        if not isinstance(bundle, dict) or "patches" not in bundle:
            return False, [], "missing 'patches' key"

        patches = bundle["patches"]
        if not isinstance(patches, list) or len(patches) == 0:
            return False, [], "patches list empty or not a list"

        workspace_root = str(Path(config.WORKSPACE_ROOT) / pack_name)
        valid_patches = []
        for i, patch in enumerate(patches):
            if not isinstance(patch, dict):
                log.warning(f"[{self.name}] Patch #{i} is not a dict — skipping")
                continue

            # All three core fields must be present
            if not all(k in patch for k in ("file", "action", "content")):
                log.warning(f"[{self.name}] Patch #{i} missing required fields — skipping")
                continue

            # Security: ensure the target file is inside the pack workspace
            target = str(Path(patch["file"]).resolve())
            if not target.startswith(workspace_root):
                log.warning(f"[{self.name}] Patch #{i} targets path outside workspace: {patch['file']} — rejected")
                continue

            if patch["action"] not in ("overwrite", "append", "insert_after"):
                log.warning(f"[{self.name}] Patch #{i} unknown action '{patch['action']}' — skipping")
                continue

            valid_patches.append(patch)

        return True, valid_patches, None

    # ------------------------------------------------------------------ #
    # Apply patches to disk
    # ------------------------------------------------------------------ #
    def _apply_patches(self, patches: list, pack_name: str) -> int:
        applied = 0
        for patch in patches:
            file_path = Path(patch["file"])
            action = patch["action"]
            content = patch["content"]
            target_line = patch.get("target_line")

            try:
                file_path.parent.mkdir(parents=True, exist_ok=True)

                if action == "overwrite":
                    file_path.write_text(content, encoding="utf-8")
                    applied += 1

                elif action == "append":
                    # Append content to existing file or create new
                    existing = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
                    file_path.write_text(existing + "\n" + content, encoding="utf-8")
                    applied += 1

                elif action == "insert_after":
                    if not file_path.exists():
                        log.warning(f"[{self.name}] insert_after: file not found: {file_path}")
                        continue
                    existing_lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
                    new_lines = []
                    inserted = False
                    for line in existing_lines:
                        new_lines.append(line)
                        if target_line and target_line in line and not inserted:
                            new_lines.append(content + "\n")
                            inserted = True
                    if not inserted:
                        # Target line not found — append at end as fallback
                        new_lines.append("\n" + content + "\n")
                        log.warning(f"[{self.name}] insert_after: target_line not found, appended at EOF")
                    file_path.write_text("".join(new_lines), encoding="utf-8")
                    applied += 1

                log.info(f"[{self.name}] Applied patch ({action}): {file_path}")

            except Exception as exc:
                log.error(f"[{self.name}] Failed to apply patch to {file_path}: {exc}")

        return applied

    # ------------------------------------------------------------------ #
    # Write SelfHealReport.json and return standard dict
    # ------------------------------------------------------------------ #
    def _write_report(
        self, report_path: Path, pack_name: str,
        pass_number: int, patches_attempted: int, patches_applied: int,
        success: bool, failed_stages: list, reason,
    ) -> dict:
        report = {
            "pack_name": pack_name,
            "pass_number": pass_number,
            "patches_attempted": patches_attempted,
            "patches_applied": patches_applied,
            "success": success,
            "failed_stages_input": failed_stages,
            "reason": reason,
        }
        report_path.write_text(json.dumps(report, indent=2))
        log.info(f"[{self.name}] SelfHeal success={success}, applied={patches_applied}/{patches_attempted}")
        return {"success": success, "patches_applied": patches_applied, "report_path": str(report_path)}
