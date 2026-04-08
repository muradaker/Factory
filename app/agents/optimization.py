"""
optimization.py — OptimizationAgent
Reviews plugin structure for production quality.
Writes OptimizationReport.json with an overall grade.
"""

import json
import re
import time
from pathlib import Path

from app.core import config, logger as log, llm_client


class OptimizationAgent:
    def __init__(self):
        self.name = "OptimizationAgent"

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    def run(self, pack_name: str) -> dict:
        workspace = Path(config.WORKSPACE_ROOT) / pack_name
        reports_dir = workspace / "Reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / "OptimizationReport.json"
        plugin_source = workspace / "PluginSource"

        log.info(f"[{self.name}] Running optimization review for '{pack_name}'")

        # ---- 1. Locate .uplugin and Build.cs ----
        uplugin_content, uplugin_ok, uplugin_issues = self._check_uplugin(plugin_source, pack_name)
        build_cs_content, build_cs_issues = self._check_build_cs(plugin_source)

        # ---- 2. Check docs ----
        docs_ok, docs_issues = self._check_docs(workspace)

        # ---- 3. Check source code quality ----
        code_quality_issues = self._check_code_quality(plugin_source)
        code_quality_issues.extend(uplugin_issues)
        code_quality_issues.extend(build_cs_issues)
        code_quality_issues.extend(docs_issues)

        # ---- 4. LLM call for production improvement suggestions ----
        llm_suggestions = self._get_llm_suggestions(pack_name, uplugin_content, build_cs_content)

        # ---- 5. Compute overall grade ----
        grade = self._compute_grade(uplugin_ok, docs_ok, code_quality_issues, llm_suggestions)

        report = {
            "pack_name": pack_name,
            "uplugin_ok": uplugin_ok,
            "docs_ok": docs_ok,
            "code_quality_issues": code_quality_issues,
            "llm_suggestions": llm_suggestions,
            "overall_grade": grade,
        }
        report_path.write_text(json.dumps(report, indent=2))
        log.info(f"[{self.name}] Optimization grade={grade}")
        return {"report_path": str(report_path), "grade": grade}

    # ------------------------------------------------------------------ #
    # Check .uplugin metadata fields
    # ------------------------------------------------------------------ #
    def _check_uplugin(self, plugin_source: Path, pack_name: str):
        required_fields = ["FriendlyName", "Description", "VersionName", "Category"]
        uplugin_files = list(plugin_source.glob("**/*.uplugin"))
        if not uplugin_files:
            return "", False, ["No .uplugin file found"]

        content = uplugin_files[0].read_text(encoding="utf-8", errors="replace")
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return content, False, [".uplugin is not valid JSON"]

        issues = []
        for field in required_fields:
            # Check presence and non-empty value
            if not data.get(field, "").strip():
                issues.append(f".uplugin missing or empty: {field}")

        ok = len(issues) == 0
        return content, ok, issues

    # ------------------------------------------------------------------ #
    # Check Build.cs for minimal dependencies
    # ------------------------------------------------------------------ #
    def _check_build_cs(self, plugin_source: Path):
        cs_files = list(plugin_source.glob("**/*.Build.cs"))
        if not cs_files:
            return "", ["No Build.cs file found"]

        content = cs_files[0].read_text(encoding="utf-8", errors="replace")
        issues = []

        # Warn if raw "Engine" module is in public dependencies without obvious justification
        if re.search(r'PublicDependencyModuleNames[^;]*"Engine"', content):
            issues.append('Build.cs: "Engine" in PublicDependencyModuleNames — verify this is intentional')

        return content, issues

    # ------------------------------------------------------------------ #
    # Check documentation files
    # ------------------------------------------------------------------ #
    def _check_docs(self, workspace: Path):
        issues = []

        readme = workspace / "README.md"
        if not readme.exists():
            issues.append("README.md missing")
        elif len(readme.read_text(encoding="utf-8", errors="replace")) <= 200:
            issues.append("README.md is too short (≤200 chars)")

        api_overview = workspace / "API_OVERVIEW.md"
        if not api_overview.exists():
            issues.append("API_OVERVIEW.md missing")

        ok = len(issues) == 0
        return ok, issues

    # ------------------------------------------------------------------ #
    # Scan generated source files for TODO / FIXME markers
    # ------------------------------------------------------------------ #
    def _check_code_quality(self, plugin_source: Path) -> list:
        issues = []
        for ext in ("*.h", "*.cpp"):
            for src_file in plugin_source.rglob(ext):
                content = src_file.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    if re.search(r'\bTODO\b|\bFIXME\b', stripped, re.IGNORECASE):
                        rel = src_file.name
                        issues.append(f"{rel}:{i}: {stripped[:120]}")
        return issues

    # ------------------------------------------------------------------ #
    # LLM call: ask for top 3 production improvements
    # ------------------------------------------------------------------ #
    def _get_llm_suggestions(self, pack_name: str, uplugin: str, build_cs: str) -> list:
        prompt = (
            f"You are reviewing a production Unreal Engine 5 plugin called '{pack_name}'.\n\n"
            f"=== .uplugin content ===\n{uplugin[:2000]}\n\n"
            f"=== Build.cs content ===\n{build_cs[:2000]}\n\n"
            "Provide exactly 3 concise, actionable improvement suggestions for production "
            "readiness on the Fab marketplace. Return a JSON array of 3 strings and nothing else."
        )
        try:
            raw = llm_client.complete(prompt, max_tokens=512)
            # Strip markdown fences if present
            clean = re.sub(r"```[a-z]*", "", raw).strip().strip("`").strip()
            suggestions = json.loads(clean)
            if isinstance(suggestions, list):
                return [str(s) for s in suggestions[:3]]
        except Exception as exc:
            log.warning(f"[{self.name}] LLM suggestions failed: {exc}")
        return ["Could not retrieve LLM suggestions"]

    # ------------------------------------------------------------------ #
    # Compute overall grade based on findings
    # ------------------------------------------------------------------ #
    def _compute_grade(self, uplugin_ok: bool, docs_ok: bool,
                       issues: list, suggestions: list) -> str:
        issue_count = len(issues)
        if uplugin_ok and docs_ok and issue_count == 0:
            return "A"
        if uplugin_ok and docs_ok and issue_count <= 3:
            return "B"
        if (uplugin_ok or docs_ok) and issue_count <= 8:
            return "C"
        return "D"
