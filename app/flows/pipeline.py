"""
pipeline.py — PluginPipeline
Orchestrates all agents in order for a single pack.
Called by: app/main.py run-job command.
"""

import time
import datetime
from pathlib import Path

from app.core.config import cfg
from app.core.logger import get_logger
from app.core.state_store import mark_done, mark_failed
from app.core.progress_tracker import update_progress

from app.agents.lead_manager import LeadManagerAgent
from app.agents.market_research import MarketResearchAgent
from app.agents.architect import ArchitectAgent
from app.agents.tech_spec import TechSpecAgent
from app.agents.senior_coder import SeniorCoderAgent
from app.agents.blueprint_builder import BlueprintBuilderAgent
from app.agents.demo_map_builder import DemoMapBuilderAgent
from app.agents.docs_agent import DocsAgent
from app.agents.function_docs import FunctionDocsAgent

logger = get_logger("pipeline")

# Stages that abort the entire pipeline on failure
CRITICAL_STAGES = {"senior_coder", "demo_map_builder"}

# Stages that only warn on failure and allow pipeline to continue
NON_CRITICAL_STAGES = {"market_research", "function_docs"}


class PluginPipeline:
    """
    Runs one complete pack through all agent stages in order.
    Handles per-stage timing, logging, state tracking, and error policy.
    """

    STAGES = [
        ("lead_manager",       LeadManagerAgent),
        ("market_research",    MarketResearchAgent),
        ("architect",          ArchitectAgent),
        ("tech_spec",          TechSpecAgent),
        ("senior_coder",       SeniorCoderAgent),
        ("blueprint_builder",  BlueprintBuilderAgent),
        ("demo_map_builder",   DemoMapBuilderAgent),
        ("docs",               DocsAgent),
        ("function_docs",      FunctionDocsAgent),
        # Part 3 agents will be appended here
    ]

    def run(self, pack_name: str) -> dict:
        """
        Run all pipeline stages for the given pack.
        Returns a summary dict with per-stage results.
        """
        logger.info(f"{'='*60}")
        logger.info(f"PluginPipeline starting for: {pack_name}")
        logger.info(f"Stages: {[s for s, _ in self.STAGES]}")
        logger.info(f"{'='*60}")

        pipeline_start = time.time()
        results = {}
        pipeline_failed = False

        for stage_name, AgentClass in self.STAGES:
            if pipeline_failed:
                logger.warning(f"[{pack_name}] Pipeline aborted. Skipping stage: {stage_name}")
                results[stage_name] = {"status": "skipped", "reason": "pipeline_aborted"}
                continue

            stage_result = self._run_stage(pack_name, stage_name, AgentClass)
            results[stage_name] = stage_result

            # Determine if pipeline should abort
            if stage_result["status"] == "failed":
                if stage_name in CRITICAL_STAGES:
                    logger.error(
                        f"[{pack_name}] CRITICAL stage '{stage_name}' failed. Aborting pipeline."
                    )
                    pipeline_failed = True
                elif stage_name in NON_CRITICAL_STAGES:
                    logger.warning(
                        f"[{pack_name}] Non-critical stage '{stage_name}' failed. Continuing pipeline."
                    )
                else:
                    logger.warning(
                        f"[{pack_name}] Stage '{stage_name}' failed. Continuing pipeline."
                    )

        elapsed = time.time() - pipeline_start
        pipeline_status = "failed" if pipeline_failed else "done"

        summary = {
            "pack_name": pack_name,
            "pipeline_status": pipeline_status,
            "elapsed_seconds": round(elapsed, 2),
            "stages": results,
            "completed_at": datetime.datetime.utcnow().isoformat() + "Z",
        }

        logger.info(f"[{pack_name}] Pipeline {pipeline_status} in {elapsed:.1f}s.")
        _write_pipeline_summary(pack_name, summary)

        return summary

    def _run_stage(self, pack_name: str, stage_name: str, AgentClass) -> dict:
        """
        Run a single stage. Returns dict with status, elapsed_seconds, result/error.
        """
        logger.info(f"[{pack_name}] ── Stage START: {stage_name} ──")
        start = time.time()

        try:
            agent = AgentClass()
            result = agent.run(pack_name)
            elapsed = time.time() - start

            # Record success in state store
            mark_done(pack_name, stage=stage_name)
            update_progress(pack_name, stage=stage_name, status="done")

            logger.info(f"[{pack_name}] ── Stage DONE: {stage_name} ({elapsed:.1f}s) ──")
            return {
                "status": "done",
                "elapsed_seconds": round(elapsed, 2),
                "result": result,
            }

        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"[{pack_name}] ── Stage FAILED: {stage_name} ({elapsed:.1f}s): {e} ──")

            # Record failure in state store
            mark_failed(pack_name, stage=stage_name, error=str(e))
            update_progress(pack_name, stage=stage_name, status="failed")

            return {
                "status": "failed",
                "elapsed_seconds": round(elapsed, 2),
                "error": str(e),
            }


def _write_pipeline_summary(pack_name: str, summary: dict) -> None:
    """Write pipeline summary JSON to workspace/{pack_name}/Reports/PipelineSummary.json."""
    import json
    report_dir = Path(cfg.get("WORKSPACE_DIR", "workspace")) / pack_name / "Reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    summary_path = report_dir / "PipelineSummary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info(f"[{pack_name}] PipelineSummary.json written: {summary_path}")
