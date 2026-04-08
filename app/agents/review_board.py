"""
review_board.py — ReviewBoardAgent
Performs a final human-like review across all QA reports.
Writes ReviewReport.json. Decision rules are enforced hard — no override.
"""

import json
import re
from pathlib import Path

from app.core import config, logger as log, llm_client, memory


# Gates that force a rejection regardless of LLM opinion
HARD_REJECT_CONDITIONS = [
    ("BuildReport.json",          lambda d: d.get("build_success") is False and not d.get("skipped")),
    ("DemoMapVerifyReport.json",  lambda d: d.get("verified") is False),
    ("RuntimeQAReport.json",      lambda d: d.get("passed") is False and not d.get("skipped")),
]


class ReviewBoardAgent:
    def __init__(self):
        self.name = "ReviewBoardAgent"

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    def run(self, pack_name: str) -> dict:
        workspace = Path(config.WORKSPACE_ROOT) / pack_name
        reports_dir = workspace / "Reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / "ReviewReport.json"

        log.info(f"[{self.name}] Starting review for '{pack_name}'")

        # ---- 1. Retrieve past review decisions for context ----
        past_decisions = memory.retrieve(category="review_decisions", query=pack_name)

        # ---- 2. Load all reports from disk ----
        all_reports = self._load_all_reports(reports_dir)

        # ---- 3. Enforce hard-reject rules before calling LLM ----
        blocking_issues = self._collect_blocking_issues(all_reports)

        # ALLOW_BUILD_SKIP=false forces rejection when build was skipped
        if not config.ALLOW_BUILD_SKIP:
            build_report = all_reports.get("BuildReport.json", {})
            if build_report.get("skipped"):
                blocking_issues.append("BUILD_WITH_UNREAL=false and ALLOW_BUILD_SKIP=false")

        # ---- 4. LLM review ----
        llm_decision, confidence, strengths, weaknesses, recommendation = self._llm_review(
            pack_name, all_reports, past_decisions
        )

        # Hard rule overrides any LLM leniency
        if blocking_issues:
            decision = "rejected"
            log.warning(f"[{self.name}] Hard-rejected due to: {blocking_issues}")
        else:
            decision = llm_decision

        report = {
            "pack_name": pack_name,
            "decision": decision,
            "confidence": confidence,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "blocking_issues": blocking_issues,
            "recommendation": recommendation,
        }
        report_path.write_text(json.dumps(report, indent=2))

        # ---- 5. Persist decision to memory for future runs ----
        memory.write(
            category="review_decisions",
            key=pack_name,
            value=json.dumps({"pack_name": pack_name, "decision": decision,
                              "blocking_issues": blocking_issues}),
        )

        log.info(f"[{self.name}] Review decision={decision}")
        return {"decision": decision, "report_path": str(report_path)}

    # ------------------------------------------------------------------ #
    # Load every .json report in the reports directory
    # ------------------------------------------------------------------ #
    def _load_all_reports(self, reports_dir: Path) -> dict:
        reports = {}
        for f in sorted(reports_dir.glob("*.json")):
            try:
                reports[f.name] = json.loads(f.read_text())
            except Exception:
                reports[f.name] = {}
        return reports

    # ------------------------------------------------------------------ #
    # Check hard-reject conditions and collect blocking issue strings
    # ------------------------------------------------------------------ #
    def _collect_blocking_issues(self, all_reports: dict) -> list:
        issues = []
        for report_name, condition_fn in HARD_REJECT_CONDITIONS:
            data = all_reports.get(report_name, {})
            try:
                if condition_fn(data):
                    issues.append(f"{report_name}: hard-reject condition triggered")
            except Exception:
                pass
        return issues

    # ------------------------------------------------------------------ #
    # LLM review call
    # ------------------------------------------------------------------ #
    def _llm_review(self, pack_name: str, all_reports: dict, past_decisions: list):
        summary = json.dumps(all_reports, indent=2)[:5000]
        past = json.dumps(past_decisions, indent=2)[:1500]

        prompt = (
            f"You are a senior review board member evaluating a production Unreal Engine 5 plugin.\n"
            f"Plugin: {pack_name}\n\n"
            f"=== All QA Reports ===\n{summary}\n\n"
            f"=== Past Review Decisions (for consistency) ===\n{past}\n\n"
            "Evaluate: code quality, docs quality, demo map, QA results, market fit, production readiness.\n"
            "Return ONLY valid JSON, no markdown:\n"
            '{"decision": "approved"|"rejected", "confidence": 0.0-1.0, '
            '"strengths": ["..."], "weaknesses": ["..."], "recommendation": "..."}'
        )

        defaults = ("rejected", 0.5, [], [], "Manual review required")
        try:
            raw = llm_client.complete(prompt, max_tokens=1024)
            clean = re.sub(r"```[a-z]*", "", raw).strip().strip("`").strip()
            data = json.loads(clean)
            return (
                data.get("decision", "rejected"),
                float(data.get("confidence", 0.5)),
                data.get("strengths", []),
                data.get("weaknesses", []),
                data.get("recommendation", ""),
            )
        except Exception as exc:
            log.error(f"[{self.name}] LLM review failed: {exc}")
            return defaults
