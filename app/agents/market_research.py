"""
MarketResearchAgent — Layer 1
Analyzes market fit and produces MarketNotes.json.
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

logger = get_logger("market_research")


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
                temperature=0.4,
            )
            return response.choices[0].message.content
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"LLM retry {attempt+1}/{max_retries}: {e}. Waiting {wait}s...")
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                raise


class MarketResearchAgent:
    """
    Layer 1 — Market Research.
    Retrieves stored market notes and produces competition/pricing analysis.
    """

    def run(self, pack_name: str) -> dict:
        logger.info(f"[{pack_name}] MarketResearchAgent starting.")

        job = load_job(pack_name)
        product_def = job.get("product_definition", {})

        # Retrieve existing market notes from memory
        retrieved = retrieve(category="market_notes", query=pack_name, top_k=5)
        market_context = "\n".join(
            r.get("value", {}).get("summary", "") if isinstance(r.get("value"), dict) else str(r.get("value", ""))
            for r in retrieved
            if isinstance(r, dict)
        )

        report_dir = Path(cfg.get("WORKSPACE_DIR", "workspace")) / pack_name / "Reports"
        report_dir.mkdir(parents=True, exist_ok=True)

        # Load prompts
        prompt_lib = _load_prompt_library()
        agent_prompts = prompt_lib.get("market_research", {})
        system_prompt = agent_prompts.get(
            "system_prompt",
            "You are a UE5 marketplace analyst. Analyze competition, pricing, and differentiation for Fab.com plugin listings."
        )
        user_template = agent_prompts.get(
            "user_prompt_template",
            "Plugin: {title}\nDescription: {description}\nTarget Audience: {target_audience}\n"
            "Existing Market Notes:\n{market_context}\n\n"
            "Respond with a JSON object: {plugin_name, market_position, price_suggestion_usd, differentiators, risks, fab_tags}"
        )

        user_prompt = user_template.format(
            title=product_def.get("title", pack_name),
            description=product_def.get("description", ""),
            target_audience=product_def.get("target_audience", "Indie/AA game developers"),
            market_context=market_context or "No prior market notes available.",
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(f"[{pack_name}] Calling LLM for market analysis...")
        raw = _llm_call_with_retry(messages)

        # Parse JSON from response
        market_notes = _parse_market_notes(raw, pack_name, product_def)

        notes_path = report_dir / "MarketNotes.json"
        notes_path.write_text(json.dumps(market_notes, indent=2), encoding="utf-8")
        logger.info(f"[{pack_name}] MarketNotes.json written to {notes_path}")

        # Store in memory for future retrievals
        write_memory(
            category="market_notes",
            key=f"{pack_name}_market_research",
            value={
                "pack_name": pack_name,
                "summary": f"Market position: {market_notes.get('market_position', 'N/A')} | "
                           f"Price: ${market_notes.get('price_suggestion_usd', 0)}",
                "data": market_notes,
            },
        )

        update_progress(pack_name, stage="market_research", status="done")

        return {"notes_path": str(notes_path), "status": "done"}


def _parse_market_notes(raw: str, pack_name: str, product_def: dict) -> dict:
    """Extract JSON market notes from LLM response, or build sensible defaults."""
    import re

    # Try to find JSON object in response
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            # Ensure required keys exist
            parsed.setdefault("plugin_name", pack_name)
            parsed.setdefault("market_position", "mid-tier")
            parsed.setdefault("price_suggestion_usd", 49.99)
            parsed.setdefault("differentiators", [])
            parsed.setdefault("risks", [])
            parsed.setdefault("fab_tags", [])
            return parsed
        except Exception:
            pass

    # Fallback defaults
    return {
        "plugin_name": pack_name,
        "market_position": "competitive mid-tier plugin addressing underserved niche",
        "price_suggestion_usd": 49.99,
        "differentiators": [
            "Full UE5.5 compatibility with GAS and enhanced input",
            "Multiplayer replication out of the box",
            "Comprehensive Blueprint exposure for designers",
        ],
        "risks": [
            "Similar free community implementations exist",
            "Requires UE5.5 which narrows initial audience",
        ],
        "fab_tags": [
            product_def.get("title", pack_name),
            "UE5",
            "Blueprint",
            "C++",
            "Multiplayer",
            "Game Systems",
        ],
    }


def _load_prompt_library() -> dict:
    """Load prompt_library.json from config/."""
    lib_path = Path("config") / "prompt_library.json"
    if lib_path.exists():
        return json.loads(lib_path.read_text(encoding="utf-8"))
    return {}
