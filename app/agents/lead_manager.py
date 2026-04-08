"""
LeadManagerAgent — Layer 1
Reads job file, produces ProductSpec.md, AcceptanceCriteria.json, JobSnapshot.json.
"""

import json
import time
import datetime
import openai
from pathlib import Path

from app.core.config import cfg
from app.core.logger import get_logger
from app.core.memory_store import write_memory
from app.core.retrieval_engine import retrieve
from app.core.progress_tracker import update_progress
from app.flows.job_loader import load_job

logger = get_logger("lead_manager")


def _llm_call_with_retry(messages: list, max_retries: int = 3) -> str:
    """Call the LLM with exponential backoff retry logic."""
    client = openai.OpenAI(
        api_key=cfg.get("OPENAI_API_KEY", "sk-placeholder"),
        base_url=cfg.get("MODEL_BASE_URL", "https://api.openai.com/v1"),
    )
    model = cfg.get("MODEL_NAME", "gpt-4o")

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
            )
            return response.choices[0].message.content
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"LLM call failed (attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait}s...")
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                raise


class LeadManagerAgent:
    """
    Layer 1 — Lead Manager.
    Produces ProductSpec.md, AcceptanceCriteria.json, JobSnapshot.json.
    """

    def run(self, pack_name: str) -> dict:
        logger.info(f"[{pack_name}] LeadManagerAgent starting.")

        # Load job definition
        job = load_job(pack_name)

        # Retrieve similar approved plugins from memory for context
        retrieved = retrieve(category="approved_plugins", query=pack_name, top_k=5)
        retrieved_summary = [r.get("summary", "") for r in retrieved if isinstance(r, dict)]

        # Build workspace reports directory
        report_dir = Path(cfg.get("WORKSPACE_DIR", "workspace")) / pack_name / "Reports"
        report_dir.mkdir(parents=True, exist_ok=True)

        # Load prompt library
        prompt_lib = _load_prompt_library()
        agent_prompts = prompt_lib.get("lead_manager", {})

        system_prompt = agent_prompts.get(
            "system_prompt",
            "You are a senior UE5.5 plugin product manager. Produce thorough product specs."
        )
        user_template = agent_prompts.get(
            "user_prompt_template",
            "Job: {job_json}\nRetrieved context: {retrieved_context}\nProduce ProductSpec.md and AcceptanceCriteria JSON."
        )

        user_prompt = user_template.format(
            job_json=json.dumps(job, indent=2),
            retrieved_context="\n".join(retrieved_summary) if retrieved_summary else "No prior context.",
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(f"[{pack_name}] Calling LLM for ProductSpec + AcceptanceCriteria...")
        raw_response = _llm_call_with_retry(messages)

        # Parse and write ProductSpec.md
        spec_path = report_dir / "ProductSpec.md"
        spec_content = _extract_section(raw_response, "PRODUCT_SPEC", fallback=raw_response)
        spec_path.write_text(spec_content, encoding="utf-8")
        logger.info(f"[{pack_name}] ProductSpec.md written to {spec_path}")

        # Parse and write AcceptanceCriteria.json
        criteria_path = report_dir / "AcceptanceCriteria.json"
        criteria = _extract_acceptance_criteria(raw_response, job)
        criteria_path.write_text(json.dumps(criteria, indent=2), encoding="utf-8")
        logger.info(f"[{pack_name}] AcceptanceCriteria.json written to {criteria_path}")

        # Write JobSnapshot.json
        snapshot_path = report_dir / "JobSnapshot.json"
        snapshot = {
            "job": job,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "retrieved_context_summary": retrieved_summary,
        }
        snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        logger.info(f"[{pack_name}] JobSnapshot.json written to {snapshot_path}")

        # Store market notes summary in memory for downstream agents
        product_def = job.get("product_definition", {})
        write_memory(
            category="market_notes",
            key=f"{pack_name}_lead_summary",
            value={
                "pack_name": pack_name,
                "summary": f"{product_def.get('title', pack_name)}: {product_def.get('description', '')}",
                "ue_version": product_def.get("ue_version", "5.5"),
            },
        )

        update_progress(pack_name, stage="lead_manager", status="done")

        return {
            "spec_path": str(spec_path),
            "criteria_path": str(criteria_path),
            "snapshot_path": str(snapshot_path),
            "status": "done",
        }


def _load_prompt_library() -> dict:
    """Load prompt_library.json from config/."""
    lib_path = Path("config") / "prompt_library.json"
    if lib_path.exists():
        return json.loads(lib_path.read_text(encoding="utf-8"))
    return {}


def _extract_section(text: str, section_marker: str, fallback: str = "") -> str:
    """Extract a named section from LLM response, or return fallback."""
    marker_start = f"<{section_marker}>"
    marker_end = f"</{section_marker}>"
    if marker_start in text and marker_end in text:
        start = text.index(marker_start) + len(marker_start)
        end = text.index(marker_end)
        return text[start:end].strip()
    return fallback.strip()


def _extract_acceptance_criteria(raw: str, job: dict) -> list:
    """
    Try to parse AcceptanceCriteria from LLM response JSON block.
    Falls back to generating sensible defaults from job scope.
    """
    # Attempt JSON extraction from response
    import re
    json_match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            if isinstance(parsed, list) and parsed:
                return parsed
        except Exception:
            pass

    # Fallback: generate criteria from implementation scope
    scope = job.get("implementation_scope", {})
    features = scope.get("core_features", [])
    criteria = []
    for feature in features:
        criteria.append({
            "criterion": f"Plugin implements {feature} as described in ProductSpec",
            "measurable": True,
            "gate": "senior_coder",
        })
    criteria.append({
        "criterion": "Plugin compiles without errors in UE5.5",
        "measurable": True,
        "gate": "build",
    })
    criteria.append({
        "criterion": "Demo map loads and contains required actors",
        "measurable": True,
        "gate": "demo_map_builder",
    })
    criteria.append({
        "criterion": "Documentation covers all public API functions",
        "measurable": True,
        "gate": "docs",
    })
    return criteria
