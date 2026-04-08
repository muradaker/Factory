"""
pipeline.py — PluginPipeline
Full autonomous production pipeline: stages 1-17 + self-heal loop.

Stages 1-9  : lead_manager → feature_spec → product_spec → architect →
              senior_coder → demo_map → demo_verify → blueprint_api → function_docs
Stages 10-16: build_fix → runtime_qa → multiplayer_qa → optimization →
              review_board → publisher → release
Self-Heal   : if release blocked → SelfHealAgent patches → retry stages 5-16
"""

import json
import time
from pathlib import Path

from app.core import config, logger as log

# ── Stages 1-9 ──────────────────────────────────────────────────────────────
from app.agents.lead_manager   import LeadManagerAgent
from app.agents.feature_spec   import FeatureSpecAgent
from app.agents.product_spec   import ProductSpecAgent
from app.agents.architect      import ArchitectAgent
from app.agents.senior_coder   import SeniorCoderAgent
from app.agents.demo_map       import DemoMapAgent
from app.agents.demo_verify    import DemoVerifyAgent
from app.agents.blueprint_api  import BlueprintAPIAgent
from app.agents.function_docs  import FunctionDocsAgent

# ── Stages 10-16 ────────────────────────────────────────────────────────────
from app.agents.build_fix      import BuildFixAgent
from app.agents.runtime_qa     import RuntimeQAAgent
from app.agents.multiplayer_qa import MultiplayerQAAgent
from app.agents.optimization   import OptimizationAgent
from app.agents.review_board   import ReviewBoardAgent
from app.agents.publisher      import PublisherAgent
from app.agents.release        import ReleaseAgent

# ── Self-heal ────────────────────────────────────────────────────────────────
from app.agents.self_heal      import SelfHealAgent


class PluginPipeline:
    def __init__(self):
        # Instantiate all agents once — they are stateless per run
        self.lead_manager    = LeadManagerAgent()
        self.feature_spec    = FeatureSpecAgent()
        self.product_spec    = ProductSpecAgent()
        self.architect       = ArchitectAgent()
        self.senior_coder    = SeniorCoderAgent()
        self.demo_map        = DemoMapAgent()
        self.demo_verify     = DemoVerifyAgent()
        self.blueprint_api   = BlueprintAPIAgent()
        self.function_docs   = FunctionDocsAgent()
        self.build_fix       = BuildFixAgent()
        self.runtime_qa      = RuntimeQAAgent()
        self.multiplayer_qa  = MultiplayerQAAgent()
        self.optimization    = OptimizationAgent()
        self.review_board    = ReviewBoardAgent()
        self.publisher       = PublisherAgent()
        self.release         = ReleaseAgent()
        self.self_heal       = SelfHealAgent()

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #
    def run(self, job: dict) -> dict:
        pack_name = job["pack_name"]
        log.info(f"[Pipeline] ══ Starting job: {pack_name} ══")
        start_total = time.time()

        # ── STAGES 1-9 ──────────────────────────────────────────────────
        s1  = self._run_stage(1,  "lead_manager",  self.lead_manager.run,  pack_name)
        s2  = self._run_stage(2,  "feature_spec",  self.feature_spec.run,  pack_name)
        s3  = self._run_stage(3,  "product_spec",  self.product_spec.run,  pack_name)
        s4  = self._run_stage(4,  "architect",     self.architect.run,     pack_name)
        s5  = self._run_stage(5,  "senior_coder",  self.senior_coder.run,  pack_name)
        s6  = self._run_stage(6,  "demo_map",      self.demo_map.run,      pack_name)
        s7  = self._run_stage(7,  "demo_verify",   self.demo_verify.run,   pack_name)
        s8  = self._run_stage(8,  "blueprint_api", self.blueprint_api.run, pack_name)
        s9  = self._run_stage(9,  "function_docs", self.function_docs.run, pack_name)

        # ── STAGES 10-16 ────────────────────────────────────────────────
        release_result = self._run_stages_10_to_16(pack_name)

        # ── SELF-HEAL LOOP ───────────────────────────────────────────────
        release_result = self._self_heal_loop(pack_name, release_result)

        # ── FINAL SUMMARY ───────────────────────────────────────────────
        total_duration = round(time.time() - start_total, 2)
        summary = self._write_final_summary(pack_name, release_result, total_duration)

        log.info(f"[Pipeline] ══ Finished: {pack_name} | approved={release_result.get('approved')} "
                 f"| {total_duration}s ══")
        return summary

    # ------------------------------------------------------------------ #
    # Run stages 10-16 as a unit (reused during self-heal retry)
    # ------------------------------------------------------------------ #
    def _run_stages_10_to_16(self, pack_name: str) -> dict:
        s10 = self._run_stage(10, "build_fix",      self.build_fix.run,      pack_name)
        s11 = self._run_stage(11, "runtime_qa",     self.runtime_qa.run,     pack_name)
        s12 = self._run_stage(12, "multiplayer_qa", self.multiplayer_qa.run, pack_name)
        s13 = self._run_stage(13, "optimization",   self.optimization.run,   pack_name)
        s14 = self._run_stage(14, "review_board",   self.review_board.run,   pack_name)
        s15 = self._run_stage(15, "publisher",      self.publisher.run,      pack_name)
        s16 = self._run_stage(16, "release",        self.release.run,        pack_name)
        return s16   # release result drives all downstream decisions

    # ------------------------------------------------------------------ #
    # Run stages 5-16 (coder + everything after) — used in self-heal retry
    # ------------------------------------------------------------------ #
    def _run_stages_5_to_16(self, pack_name: str) -> dict:
        self._run_stage(5,  "senior_coder",  self.senior_coder.run,  pack_name)
        self._run_stage(6,  "demo_map",      self.demo_map.run,      pack_name)
        self._run_stage(7,  "demo_verify",   self.demo_verify.run,   pack_name)
        self._run_stage(8,  "blueprint_api", self.blueprint_api.run, pack_name)
        self._run_stage(9,  "function_docs", self.function_docs.run, pack_name)
        return self._run_stages_10_to_16(pack_name)

    # ------------------------------------------------------------------ #
    # Self-heal loop: patch → retry until approved or max passes reached
    # ------------------------------------------------------------------ #
    def _self_heal_loop(self, pack_name: str, release_result: dict) -> dict:
        # Check feature flags
        self_heal_enabled = getattr(config, "SELF_HEAL_ENABLED", True)
        max_passes = int(getattr(config, "SELF_HEAL_MAX_PASSES", 3))

        if not self_heal_enabled:
            log.info("[Pipeline] Self-heal disabled — skipping")
            return release_result

        pass_number = 1

        while not release_result.get("approved", False) and pass_number <= max_passes:
            log.info(f"[Pipeline] Self-heal pass #{pass_number} of {max_passes}")

            # Determine which stages failed to give the healer context
            failed_stages = self._collect_failed_stages(pack_name)

            heal_result = self.self_heal.run(
                pack_name=pack_name,
                pass_number=pass_number,
                failed_stages=failed_stages,
            )

            if not heal_result.get("success") or heal_result.get("patches_applied", 0) == 0:
                log.warning(f"[Pipeline] Self-heal pass #{pass_number}: no patches applied — stopping")
                break

            log.info(f"[Pipeline] Patches applied: {heal_result['patches_applied']} — retrying stages 5-16")
            release_result = self._run_stages_5_to_16(pack_name)
            pass_number += 1

        if release_result.get("approved"):
            log.info("[Pipeline] Self-heal: pipeline approved ✓")
        else:
            log.warning(f"[Pipeline] Self-heal exhausted after {pass_number - 1} pass(es) — still not approved")

        return release_result

    # ------------------------------------------------------------------ #
    # Collect names of failed stages by scanning reports
    # ------------------------------------------------------------------ #
    def _collect_failed_stages(self, pack_name: str) -> list:
        reports_dir = Path(config.WORKSPACE_ROOT) / pack_name / "Reports"
        failed = []

        # Map each report to its logical stage name
        report_stage_map = {
            "BuildReport.json":              ("build_fix",      lambda d: not d.get("build_success")),
            "RuntimeQAReport.json":          ("runtime_qa",     lambda d: not d.get("passed")),
            "MultiplayerSmokeTestReport.json":("multiplayer_qa", lambda d: d.get("status") == "failed"),
            "OptimizationReport.json":       ("optimization",   lambda d: d.get("overall_grade") in ("C","D")),
            "ReviewReport.json":             ("review_board",   lambda d: d.get("decision") != "approved"),
            "PipelineSummary.json":          ("release",        lambda d: not d.get("approved")),
        }

        for filename, (stage_name, fail_fn) in report_stage_map.items():
            path = reports_dir / filename
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text())
                if fail_fn(data):
                    failed.append(stage_name)
            except Exception:
                pass

        return failed

    # ------------------------------------------------------------------ #
    # Write the final PipelineSummary.json
    # ------------------------------------------------------------------ #
    def _write_final_summary(self, pack_name: str, release_result: dict, duration: float) -> dict:
        reports_dir = Path(config.WORKSPACE_ROOT) / pack_name / "Reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        summary_path = reports_dir / "PipelineSummary.json"

        # Attempt to load the existing PipelineSummary written by ReleaseAgent
        existing = {}
        if summary_path.exists():
            try:
                existing = json.loads(summary_path.read_text())
            except Exception:
                pass

        # Merge with pipeline-level metadata
        summary = {
            **existing,
            "pack_name": pack_name,
            "approved": release_result.get("approved", False),
            "zip_path": release_result.get("zip_path"),
            "total_duration_s": duration,
            "pipeline_complete": True,
        }
        summary_path.write_text(json.dumps(summary, indent=2))
        return summary

    # ------------------------------------------------------------------ #
    # Thin wrapper: run one stage, log start/end, return result safely
    # ------------------------------------------------------------------ #
    def _run_stage(self, number: int, name: str, fn, pack_name: str) -> dict:
        log.info(f"[Pipeline] ── Stage {number:02d}: {name} ──")
        start = time.time()
        try:
            result = fn(pack_name)
        except Exception as exc:
            log.error(f"[Pipeline] Stage {number} ({name}) raised exception: {exc}")
            result = {"error": str(exc), "stage": name}
        elapsed = round(time.time() - start, 2)
        log.info(f"[Pipeline] Stage {number:02d} done in {elapsed}s")
        return result or {}
