"""
ArchitectAgent — Layer 2
Designs UE5.5 plugin system architecture from ProductSpec + MarketNotes.
Produces GeneratedArchitecture.txt (500+ words).
"""

import json
import time
import openai
from pathlib import Path

from app.core.config import cfg
from app.core.logger import get_logger
from app.core.memory_store import write_memory
from app.core.retrieval_engine import retrieve
from app.core.progress_tracker import update_progress
from app.flows.job_loader import load_job

logger = get_logger("architect")


def _llm_call_with_retry(messages: list, max_retries: int = 3) -> str:
    """LLM call with exponential backoff."""
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
                max_tokens=4096,
            )
            return response.choices[0].message.content
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"LLM retry {attempt+1}/{max_retries}: {e}. Waiting {wait}s...")
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                raise


class ArchitectAgent:
    """
    Layer 2 — Architect.
    Produces GeneratedArchitecture.txt with full UE5.5 plugin design.
    """

    def run(self, pack_name: str) -> dict:
        logger.info(f"[{pack_name}] ArchitectAgent starting.")

        job = load_job(pack_name)
        report_dir = Path(cfg.get("WORKSPACE_DIR", "workspace")) / pack_name / "Reports"
        report_dir.mkdir(parents=True, exist_ok=True)

        # Read ProductSpec.md produced by LeadManagerAgent
        spec_path = report_dir / "ProductSpec.md"
        product_spec = spec_path.read_text(encoding="utf-8") if spec_path.exists() else "No spec available."

        # Read MarketNotes.json from MarketResearchAgent
        notes_path = report_dir / "MarketNotes.json"
        market_notes = {}
        if notes_path.exists():
            market_notes = json.loads(notes_path.read_text(encoding="utf-8"))

        # Retrieve architecture patterns from memory
        retrieved = retrieve(category="architecture_patterns", query=pack_name, top_k=5)
        arch_context = "\n".join(
            r.get("value", {}).get("summary", "") if isinstance(r.get("value"), dict) else str(r.get("value", ""))
            for r in retrieved
            if isinstance(r, dict)
        )

        product_def = job.get("product_definition", {})
        scope = job.get("implementation_scope", {})

        prompt_lib = _load_prompt_library()
        agent_prompts = prompt_lib.get("architect", {})
        system_prompt = agent_prompts.get(
            "system_prompt",
            (
                "You are a senior Unreal Engine 5.5 plugin architect. "
                "Design production-quality C++ plugin architectures. "
                "Always specify module splits, class hierarchies, interfaces, replication approach, and folder structure."
            ),
        )
        user_template = agent_prompts.get(
            "user_prompt_template",
            (
                "Plugin: {title}\nDescription: {description}\nMultiplayer: {multiplayer}\n"
                "Core Features: {features}\nC++ Modules: {modules}\n"
                "Product Spec:\n{spec}\n"
                "Market Notes:\n{market}\n"
                "Prior Architecture Patterns:\n{arch_context}\n\n"
                "Produce a FULL UE5.5 plugin architecture document (minimum 500 words) covering:\n"
                "1. Module list with runtime/editor split\n"
                "2. Complete class list with responsibilities\n"
                "3. Key interfaces (UInterfaces)\n"
                "4. Replication approach (if multiplayer)\n"
                "5. GAS integration points (if applicable)\n"
                "6. Folder structure tree\n"
                "7. Third-party dependencies\n"
                "8. Blueprint exposure strategy\n"
            ),
        )

        user_prompt = user_template.format(
            title=product_def.get("title", pack_name),
            description=product_def.get("description", ""),
            multiplayer=product_def.get("multiplayer_aware", False),
            features=json.dumps(scope.get("core_features", []), indent=2),
            modules=json.dumps(scope.get("c_plus_plus_modules", []), indent=2),
            spec=product_spec[:3000],
            market=json.dumps(market_notes, indent=2)[:1000],
            arch_context=arch_context or "No prior patterns available.",
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(f"[{pack_name}] Calling LLM for architecture design...")
        arch_text = _llm_call_with_retry(messages)

        # Ensure minimum length
        if len(arch_text.split()) < 500:
            logger.warning(f"[{pack_name}] Architecture too short ({len(arch_text.split())} words). Requesting expansion.")
            expand_messages = messages + [
                {"role": "assistant", "content": arch_text},
                {"role": "user", "content": "The architecture document is too brief. Expand it significantly — add more detail to every section, especially class responsibilities, replication, and folder structure. Minimum 500 words total."},
            ]
            arch_text = _llm_call_with_retry(expand_messages)

        arch_path = report_dir / "GeneratedArchitecture.txt"
        arch_path.write_text(arch_text, encoding="utf-8")
        logger.info(f"[{pack_name}] GeneratedArchitecture.txt written ({len(arch_text.split())} words).")

        # Store pattern in memory for future packs
        write_memory(
            category="architecture_patterns",
            key=f"{pack_name}_architecture",
            value={
                "pack_name": pack_name,
                "summary": f"Architecture for {pack_name}: {arch_text[:300]}...",
                "modules": scope.get("c_plus_plus_modules", []),
                "multiplayer": product_def.get("multiplayer_aware", False),
            },
        )

        update_progress(pack_name, stage="architect", status="done")

        return {"arch_path": str(arch_path), "status": "done"}


def _load_prompt_library() -> dict:
    """Load config/prompt_library.json."""
    lib_path = Path("config") / "prompt_library.json"
    if lib_path.exists():
        return json.loads(lib_path.read_text(encoding="utf-8"))
    return {}
